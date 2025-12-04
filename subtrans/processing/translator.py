"""Translation logic using OpenAI GPT models."""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pysrt
from openai import OpenAI, RateLimitError
from openai.types.chat.chat_completion import ChatCompletion
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeRemainingColumn,
)

from ..core.models import TranslationContext
from ..core.utils import console


# Directory containing prompt templates
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


# Allow overriding in tests to avoid sleeps
def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _retry_delay_from_error(error: RateLimitError, fallback: float) -> float:
    """Extract Retry-After header if available, otherwise use fallback."""
    try:
        headers = getattr(error, "response", None)
        header_dict = getattr(headers, "headers", {}) if headers else {}
        retry_after = header_dict.get("retry-after") or header_dict.get("Retry-After")
        if retry_after:
            return float(retry_after)
    except Exception:
        # If anything goes wrong, just fall back to default
        pass
    return fallback


def _calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two texts.

    Returns a value from 0.0 (identical) to 1.0 (completely different).
    Uses difflib.SequenceMatcher for character-based comparison.

    Args:
        text1: First text to compare
        text2: Second text to compare

    Returns:
        Difference ratio (1.0 - similarity)
    """
    from difflib import SequenceMatcher

    # Normalize: lowercase, strip whitespace
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()

    # Edge cases
    if not t1 and not t2:
        return 0.0  # Both empty = identical
    if not t1 or not t2:
        return 1.0  # One empty = completely different

    # Calculate similarity using SequenceMatcher
    matcher = SequenceMatcher(None, t1, t2)
    similarity = matcher.ratio()

    # Return difference (1.0 - similarity)
    return 1.0 - similarity


def _validate_translation_quality(
    original: str,
    translated: str,
    min_difference: float = 0.8,
) -> tuple[bool, float]:
    """
    Validate that translation is sufficiently different from original.

    This helps detect cases where the API returns untranslated or
    insufficiently translated text.

    Args:
        original: Original subtitle text
        translated: Translated subtitle text
        min_difference: Minimum difference ratio (0.0-1.0)

    Returns:
        Tuple of (is_valid, actual_difference)
    """
    difference = _calculate_text_similarity(original, translated)
    is_valid = difference >= min_difference

    return is_valid, difference


def load_analysis_prompt(source_lang: str, target_lang: str) -> str:
    """
    Load analysis prompt from external text file.

    Tries to load language-specific prompt (e.g., analysis_prompt.fi.txt),
    falls back to generic prompt (analysis_prompt.txt).

    Args:
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        Prompt text with {source_lang} and {target_lang} substituted
    """
    # Try language-specific prompt first
    lang_specific_path = PROMPTS_DIR / f"analysis_prompt.{target_lang}.txt"
    generic_path = PROMPTS_DIR / "analysis_prompt.txt"

    prompt_path = lang_specific_path if lang_specific_path.exists() else generic_path

    try:
        with open(prompt_path, encoding="utf-8") as f:
            prompt_template = f.read()
            # Only substitute language placeholders if they exist in the template
            if "{source_lang}" in prompt_template or "{target_lang}" in prompt_template:
                return prompt_template.format(
                    source_lang=source_lang, target_lang=target_lang
                )
            return prompt_template
    except FileNotFoundError:
        console.print(
            f"[yellow]Warning: Could not find prompt file at {prompt_path}. "
            "Using fallback prompt.[/yellow]"
        )
        # Fallback to a minimal generic prompt
        return f"""Analyze these movie subtitles and extract information needed for {source_lang} to {target_lang} translation.
Return a JSON object with: characters, places, recurring_terms, genre, tone, formality, style_notes."""
    except Exception as e:
        console.print(
            f"[yellow]Warning: Error loading prompt file: {e}. "
            "Using fallback prompt.[/yellow]"
        )
        return f"""Analyze these movie subtitles and extract information needed for {source_lang} to {target_lang} translation.
Return a JSON object with: characters, places, recurring_terms, genre, tone, formality, style_notes."""


def _call_with_retries(
    request_fn: Callable[[], Any],
    *,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
) -> Any:
    """
    Call an OpenAI request function with bounded retries and exponential backoff.
    Raises the last exception if all attempts fail.
    """
    from openai import RateLimitError

    last_exception: RateLimitError | Exception | None = None

    for attempt in range(max_attempts):
        try:
            return request_fn()
        except RateLimitError as e:
            last_exception = e
            if attempt == max_attempts - 1:
                raise
            delay = _retry_delay_from_error(e, backoff_base * (2**attempt))
            console.print(
                f"[yellow]Rate limit hit. Retrying in {delay:.1f}s "
                f"({attempt + 1}/{max_attempts})[/yellow]"
            )
            _sleep(delay)
        except Exception as e:
            last_exception = e
            if attempt == max_attempts - 1:
                raise
            delay = backoff_base * (2**attempt)
            console.print(
                f"[yellow]OpenAI request failed ({e}); retrying in {delay:.1f}s "
                f"({attempt + 1}/{max_attempts})[/yellow]"
            )
            _sleep(delay)

    # Should not reach here, but raise last exception to be safe
    if last_exception:
        raise last_exception

    # This should never be reached, but mypy needs it
    raise RuntimeError("Unexpected error: all attempts failed without raising")


def analyze_subtitles(
    subs: pysrt.SubRipFile,
    client: OpenAI,
    movie_title: str,
    model: str = "gpt-4o",
    source_lang: str = "en",
    target_lang: str = "fi",
) -> TranslationContext:
    """
    First pass: Analyze full subtitle file to extract translation context.

    Args:
        subs: Subtitle file to analyze
        client: OpenAI client
        movie_title: Movie title for context
        model: OpenAI model to use
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        TranslationContext with extracted metadata
    """
    console.print("[blue]Pass 1: Analyzing subtitle content...[/blue]")

    # Combine all subtitle text
    full_text = "\n".join(sub.text.replace("\n", " ") for sub in subs)

    # Load analysis prompt from external file (language-specific or generic)
    analysis_prompt = load_analysis_prompt(source_lang, target_lang)

    try:
        response = _call_with_retries(
            lambda: client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": f"""
You are an expert audiovisual translator and linguist analyzing subtitles for the movie: {movie_title}.

Source language: English
Target language: Finnish

Your task is to read the subtitles and produce a concise JSON "translation context" object that will be used by another model to translate the subtitles into Finnish.

Requirements:
- Focus on names, places, recurring terms, and domain-specific terminology that must be translated consistently.
- Prefer professional Finnish subtitle style and terminology.
- If you are uncertain about something, either omit it or mark it as needing review instead of inventing details.
- Your reply MUST be a single valid JSON object and nothing else.
""",
                    },
                    {
                        "role": "user",
                        "content": f"{analysis_prompt}\n\nSubtitles:\n{full_text}",
                    },
                ],
                response_format={"type": "json_object"},
                timeout=60,
            )
        )
        response = cast(ChatCompletion, response)

        content = response.choices[0].message.content
        if content is None:
            raise ValueError("OpenAI API returned empty content for analysis")
        result = json.loads(content)

        # Extract formality: use formality_recommendation for Finnish, formality_guidance for others
        formality = result.get("formality_recommendation") or result.get(
            "formality_guidance"
        )

        console.print(
            f"[green]Found {len(result.get('characters', {}))} characters, "
            f"{len(result.get('places', {}))} places, "
            f"{len(result.get('recurring_terms', {}))} recurring terms[/green]"
        )
        console.print(
            f"[green]Genre: {result.get('genre')}, Tone: {result.get('tone')}, "
            f"Formality: {formality or 'N/A'}[/green]"
        )

        return TranslationContext(
            characters=result.get("characters", {}),
            places=result.get("places", {}),
            terms=result.get("recurring_terms", {}),
            genre=result.get("genre", "unknown"),
            tone=result.get("tone", "mixed"),
            formality=formality,
            style_notes=result.get("style_notes", ""),
            domains=result.get("domains", []),
            domain_glossaries=result.get("domain_glossaries", {}),
            raw_json=result,
        )

    except RateLimitError as e:
        console.print(
            "[red]OpenAI API quota exceeded![/red]\n"
            "You have exceeded your current OpenAI API quota.\n"
            "Please check your plan and billing details at:\n"
            "https://platform.openai.com/account/billing\n"
        )
        raise SystemExit(1) from e
    except Exception as e:
        console.print(
            f"[yellow]Analysis failed: {e}. Proceeding without context.[/yellow]"
        )
        return TranslationContext(
            characters={},
            places={},
            terms={},
            genre="unknown",
            tone="mixed",
            formality=None,
            style_notes="",
            domains=[],
            domain_glossaries={},
            raw_json={},
        )


def build_translation_prompt(
    movie_title: str,
    context: TranslationContext,
    source_lang: str = "en",
    target_lang: str = "fi",
) -> str:
    """
    Build system prompt incorporating extracted context.

    Args:
        movie_title: Movie title
        context: Translation context from analysis
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)

    Returns:
        System prompt string for translation
    """
    # Format character list
    char_list = ""
    if context.characters:
        char_items = [f"  - {src}: {tgt}" for src, tgt in context.characters.items()]
        char_list = "Character names:\n" + "\n".join(char_items)

    # Format place list
    place_list = ""
    if context.places:
        place_items = [f"  - {src}: {tgt}" for src, tgt in context.places.items()]
        place_list = "Place names:\n" + "\n".join(place_items)

    # Format recurring terms
    term_list = ""
    if context.terms:
        term_items = [f'  - "{src}" -> "{tgt}"' for src, tgt in context.terms.items()]
        term_list = "Recurring terms/phrases:\n" + "\n".join(term_items)

    # Format domain glossaries
    domain_glossary_text = ""
    if context.domains and context.domain_glossaries:
        glossary_sections = []
        for domain in context.domains:
            if domain in context.domain_glossaries:
                terms = context.domain_glossaries[domain]
                term_items = [f'  - "{en}" -> "{fi}"' for en, fi in terms.items()]
                glossary_sections.append(
                    f"{domain.replace('_', ' ').title()}:\n" + "\n".join(term_items)
                )

        if glossary_sections:
            domain_glossary_text = "Domain-specific terminology:\n" + "\n\n".join(
                glossary_sections
            )

    # Use specialized prompt for English → Finnish, generic for others
    if source_lang == "en" and target_lang == "fi":
        return f"""You are a professional subtitle translator specializing in English to Finnish translation.
You are translating subtitles for: {movie_title}

MOVIE CONTEXT:
- Genre: {context.genre}
- Tone: {context.tone}
- Use {'formal "te"' if context.formality == "te" else 'informal "sinä"'} for "you" (unless context clearly requires otherwise)
{f"- Style notes: {context.style_notes}" if context.style_notes else ""}

TERMINOLOGY (use consistently):
{char_list if char_list else "(No specific character name guidance)"}

{place_list if place_list else ""}

{term_list if term_list else ""}

{domain_glossary_text if domain_glossary_text else ""}

TRANSLATION GUIDELINES:
- Translate naturally into Finnish, not word-for-word
- Maintain the {context.tone} tone throughout
- Keep interjections natural in Finnish (e.g., "Oh" -> "Voi", "Hey" -> "Hei", "Yeah" -> "Joo")
- Keep translations concise to fit on screen (similar length to original)
- Handle idioms appropriately for Finnish audience
- Preserve emphasis and emotion from original

Return ONLY the translated Finnish text, maintaining the exact same number of subtitles as the input.
Separate each translation with exactly this pattern on its own line: [NEXT]

CRITICAL FORMATTING RULES:
- Each subtitle translation should be on a single line (no line breaks within a translation)
- Put [NEXT] on its own line between translations
- Do not add numbering, timestamps, or any other formatting
- The total number of translations must match the input exactly

Example format for 3 subtitles:
First subtitle translation here
[NEXT]
Second subtitle translation here
[NEXT]
Third subtitle translation here"""
    else:
        # Generic prompt for other language pairs
        formality_note = f"\n- {context.formality}" if context.formality else ""

        return f"""You are a professional subtitle translator specializing in {source_lang} to {target_lang} translation.
You are translating subtitles for: {movie_title}

MOVIE CONTEXT:
- Genre: {context.genre}
- Tone: {context.tone}{formality_note}
{f"- Style notes: {context.style_notes}" if context.style_notes else ""}

TERMINOLOGY (use consistently):
{char_list if char_list else "(No specific character name guidance)"}

{place_list if place_list else ""}

{term_list if term_list else ""}

{domain_glossary_text if domain_glossary_text else ""}

TRANSLATION GUIDELINES:
- Translate naturally into {target_lang}, not word-for-word
- Maintain the {context.tone} tone throughout
- Keep translations concise to fit on screen (similar length to original)
- Handle idioms and cultural references appropriately for {target_lang} audience
- Preserve emphasis and emotion from original
- Maintain consistency with the terminology guidance above

Return ONLY the translated {target_lang} text, maintaining the exact same number of subtitles as the input.
Separate each translation with exactly this pattern on its own line: [NEXT]

CRITICAL FORMATTING RULES:
- Each subtitle translation should be on a single line (no line breaks within a translation)
- Put [NEXT] on its own line between translations
- Do not add numbering, timestamps, or any other formatting
- The total number of translations must match the input exactly

Example format for 3 subtitles:
First subtitle translation here
[NEXT]
Second subtitle translation here
[NEXT]
Third subtitle translation here"""


def translate_subtitles_batch(
    subs: pysrt.SubRipFile,
    client: OpenAI,
    movie_title: str,
    context: TranslationContext | None = None,
    batch_size: int = 50,
    model: str = "gpt-4o",
    source_lang: str = "en",
    target_lang: str = "fi",
    validate_translation: bool = True,
    min_translation_difference: float = 0.8,
) -> pysrt.SubRipFile:
    """
    Second pass: Translate subtitles in batches using extracted context.

    Args:
        subs: Subtitle file to translate
        client: OpenAI client
        movie_title: Movie title for context
        context: Translation context from analysis (optional)
        batch_size: Number of subtitles per API call
        model: OpenAI model to use
        source_lang: Source language code (ISO 639-1/2)
        target_lang: Target language code (ISO 639-1/2)
        validate_translation: Whether to validate translation quality
        min_translation_difference: Minimum difference ratio (0.0-1.0)

    Returns:
        Translated subtitle file
    """
    translated = pysrt.SubRipFile()
    total_batches = (len(subs) + batch_size - 1) // batch_size

    # Build prompt with or without context
    if context:
        system_prompt = build_translation_prompt(
            movie_title, context, source_lang, target_lang
        )
    else:
        # Fallback prompt when no context is available
        if source_lang == "en" and target_lang == "fi":
            system_prompt = f"""You are a professional subtitle translator specializing in English to Finnish translation.
You are translating subtitles for: {movie_title}

Guidelines:
- Translate naturally into Finnish, not word-for-word
- Use informal "sinä" for "you" unless context suggests formal
- Keep interjections natural in Finnish
- Keep translations concise to fit on screen
- Handle idioms appropriately for Finnish audience

Return ONLY the translated Finnish text, maintaining the exact same number of subtitles as the input.
Separate each translation with exactly this pattern on its own line: [NEXT]

CRITICAL FORMATTING RULES:
- Each subtitle translation should be on a single line (no line breaks within a translation)
- Put [NEXT] on its own line between translations
- Do not add numbering, timestamps, or any other formatting
- The total number of translations must match the input exactly

Example format for 3 subtitles:
First subtitle translation here
[NEXT]
Second subtitle translation here
[NEXT]
Third subtitle translation here"""
        else:
            system_prompt = f"""You are a professional subtitle translator specializing in {source_lang} to {target_lang} translation.
You are translating subtitles for: {movie_title}

Guidelines:
- Translate naturally into {target_lang}, not word-for-word
- Keep translations concise to fit on screen
- Handle idioms and cultural references appropriately

Return ONLY the translated {target_lang} text, maintaining the exact same number of subtitles as the input.
Separate each translation with exactly this pattern on its own line: [NEXT]

CRITICAL FORMATTING RULES:
- Each subtitle translation should be on a single line (no line breaks within a translation)
- Put [NEXT] on its own line between translations
- Do not add numbering, timestamps, or any other formatting
- The total number of translations must match the input exactly

Example format for 3 subtitles:
First subtitle translation here
[NEXT]
Second subtitle translation here
[NEXT]
Third subtitle translation here"""

    console.print(
        f"[blue]Pass 2: Translating {len(subs)} subtitles in {total_batches} batches...[/blue]"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("{task.completed}/{task.total} batches"),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Translating", total=total_batches)

        for i in range(0, len(subs), batch_size):
            batch = subs[i : i + batch_size]

            # Prepare batch text with clear separators
            batch_texts = [sub.text.replace("\n", " ") for sub in batch]
            input_text = "\n[NEXT]\n".join(batch_texts)

            # Add context about position in movie
            position_note = ""
            if i == 0:
                position_note = "(Beginning of movie)\n\n"
            elif i + batch_size >= len(subs):
                position_note = "(End of movie)\n\n"

            translations: list[str] | None = None

            for attempt in range(2):
                try:
                    response = _call_with_retries(
                        lambda: client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {
                                    "role": "user",
                                    "content": f"{position_note}Translate to {target_lang}:\n\n{input_text}",
                                },
                            ],
                            timeout=60,
                        )
                    )
                    response = cast(ChatCompletion, response)

                    content = response.choices[0].message.content
                    if content is None:
                        raise ValueError(
                            "OpenAI API returned empty content for translation"
                        )
                    translated_text = content.strip()

                    # Try splitting by separator with newlines
                    translations = [
                        t.strip()
                        for t in translated_text.split("\n[NEXT]\n")
                        if t.strip()
                    ]

                    # If that didn't work, try without newlines
                    if len(translations) == 1 and len(batch) > 1:
                        translations = [
                            t.strip()
                            for t in translated_text.split("[NEXT]")
                            if t.strip()
                        ]

                    # Last resort: try splitting by newlines
                    if len(translations) == 1 and len(batch) > 1:
                        fallback_translations = [
                            t.strip()
                            for t in translated_text.split("\n")
                            if t.strip() and t.strip() != "[NEXT]"
                        ]
                        # ONLY use fallback if it gives exactly the right count
                        if len(fallback_translations) == len(batch):
                            translations = fallback_translations
                        # Otherwise keep as 1 item, will trigger error and retry

                    if len(translations) != len(batch):
                        # Log first 300 chars of response for debugging
                        console.print(
                            f"[yellow]Response preview: {translated_text[:300]}...[/yellow]"
                        )
                        raise ValueError(
                            f"Expected {len(batch)} translations, got {len(translations)}"
                        )

                    break

                except RateLimitError as e:
                    batch_num = i // batch_size + 1
                    console.print(
                        f"\n[red]OpenAI API quota exceeded at batch {batch_num}![/red]\n"
                        "You have exceeded your current OpenAI API quota.\n"
                        "Please check your plan and billing details at:\n"
                        "https://platform.openai.com/account/billing\n\n"
                        f"Progress: {batch_num - 1}/{total_batches} batches completed.\n"
                    )
                    raise SystemExit(1) from e
                except Exception as e:
                    translations = None
                    if attempt == 1:
                        console.print(
                            f"[red]Translation error in batch {i // batch_size + 1}: {e}[/red]"
                        )
                    else:
                        delay = min(2**attempt, 5)
                        console.print(
                            f"[yellow]Retrying batch {i // batch_size + 1} after error: {e}[/yellow]"
                        )
                        _sleep(delay)

            if translations is None:
                # Keep original text on error
                for sub in batch:
                    translated.append(sub)
            else:
                # Validate batch quality if enabled (compare entire batch at once)
                if validate_translation:
                    # Combine original batch texts
                    original_batch_text = " ".join(sub.text for sub in batch)
                    # Combine translated batch texts
                    translated_batch_text = " ".join(translations)

                    # Check if entire batch is sufficiently different
                    is_valid, difference = _validate_translation_quality(
                        original_batch_text,
                        translated_batch_text,
                        min_difference=min_translation_difference,
                    )

                    if not is_valid:
                        batch_num = i // batch_size + 1
                        console.print(
                            f"[yellow]Warning: Batch {batch_num} appears untranslated "
                            f"(only {difference:.1%} different from original)[/yellow]"
                        )

                # Create translated subtitle items
                for j, sub in enumerate(batch):
                    new_sub = pysrt.SubRipItem(
                        index=sub.index,
                        start=sub.start,
                        end=sub.end,
                        text=translations[j].strip(),
                    )
                    translated.append(new_sub)

            progress.update(task, advance=1)

    return translated
