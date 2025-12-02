"""Translation logic using OpenAI GPT models."""

import json

import pysrt
from openai import OpenAI
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeRemainingColumn,
)

from ..core.models import TranslationContext
from ..core.utils import console


def analyze_subtitles(
    subs: pysrt.SubRipFile,
    client: OpenAI,
    movie_title: str,
    model: str = "gpt-4",
) -> TranslationContext:
    """
    First pass: Analyze full subtitle file to extract translation context.

    Args:
        subs: Subtitle file to analyze
        client: OpenAI client
        movie_title: Movie title for context
        model: OpenAI model to use

    Returns:
        TranslationContext with extracted metadata
    """
    console.print("[blue]Pass 1: Analyzing subtitle content...[/blue]")

    # Combine all subtitle text
    full_text = "\n".join(sub.text.replace("\n", " ") for sub in subs)

    analysis_prompt = """Analyze these movie subtitles and extract information needed for English to Finnish translation.

Return a JSON object with:
{
    "characters": {
        "CharacterName": "keep|translate|note",
        // For each character, indicate:
        // - "keep" if name should stay in English (e.g., "Jack" -> "Jack")
        // - "translate" if there's a Finnish equivalent (e.g., "John" -> "Juha")
        // - Or provide the Finnish version/note (e.g., "Johnny" -> "kept as Johnny, nicknamed 'Joni' by friends")
    },
    "places": {
        "PlaceName": "keep|Finnish equivalent|note"
    },
    "recurring_terms": {
        // Catchphrases, technical terms, made-up words that appear multiple times
        "English term": "suggested Finnish translation or handling"
    },
    "genre": "action|comedy|drama|horror|sci-fi|fantasy|thriller|romance|documentary|animated|other",
    "tone": "serious|humorous|dark|lighthearted|mixed",
    "formality": "formal|informal|mixed",
    "formality_recommendation": "te|sinä",  // Which Finnish 'you' form to use predominantly
    "style_notes": "Any other notes about language style, slang, accents, time period, etc. that would help translation"
}

Focus on consistency - the goal is to make sure the same names/terms are translated the same way throughout."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"You are analyzing subtitles for: {movie_title}",
                },
                {
                    "role": "user",
                    "content": f"{analysis_prompt}\n\nSubtitles:\n{full_text}",
                },
            ],
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)

        console.print(
            f"[green]Found {len(result.get('characters', {}))} characters, "
            f"{len(result.get('places', {}))} places, "
            f"{len(result.get('recurring_terms', {}))} recurring terms[/green]"
        )
        console.print(
            f"[green]Genre: {result.get('genre')}, Tone: {result.get('tone')}, "
            f"Formality: {result.get('formality_recommendation', 'sinä')}[/green]"
        )

        return TranslationContext(
            characters=result.get("characters", {}),
            places=result.get("places", {}),
            terms=result.get("recurring_terms", {}),
            genre=result.get("genre", "unknown"),
            tone=result.get("tone", "mixed"),
            formality=result.get("formality_recommendation", "sinä"),
            style_notes=result.get("style_notes", ""),
            raw_json=result,
        )

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
            formality="sinä",
            style_notes="",
            raw_json={},
        )


def build_translation_prompt(movie_title: str, context: TranslationContext) -> str:
    """
    Build system prompt incorporating extracted context.

    Args:
        movie_title: Movie title
        context: Translation context from analysis

    Returns:
        System prompt string for translation
    """
    # Format character list
    char_list = ""
    if context.characters:
        char_items = [f"  - {eng}: {fin}" for eng, fin in context.characters.items()]
        char_list = "Character names:\n" + "\n".join(char_items)

    # Format place list
    place_list = ""
    if context.places:
        place_items = [f"  - {eng}: {fin}" for eng, fin in context.places.items()]
        place_list = "Place names:\n" + "\n".join(place_items)

    # Format recurring terms
    term_list = ""
    if context.terms:
        term_items = [f'  - "{eng}" -> "{fin}"' for eng, fin in context.terms.items()]
        term_list = "Recurring terms/phrases:\n" + "\n".join(term_items)

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

TRANSLATION GUIDELINES:
- Translate naturally into Finnish, not word-for-word
- Maintain the {context.tone} tone throughout
- Keep interjections natural in Finnish (e.g., "Oh" -> "Voi", "Hey" -> "Hei", "Yeah" -> "Joo")
- Keep translations concise to fit on screen (similar length to original)
- Handle idioms appropriately for Finnish audience
- Preserve emphasis and emotion from original

Return ONLY the translated text, one subtitle per line, in the same order as input.
Use "---" as separator between subtitles. Do not add numbering or timestamps."""


def translate_subtitles_batch(
    subs: pysrt.SubRipFile,
    client: OpenAI,
    movie_title: str,
    context: TranslationContext | None = None,
    batch_size: int = 50,
    model: str = "gpt-4",
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

    Returns:
        Translated subtitle file
    """
    translated = pysrt.SubRipFile()
    total_batches = (len(subs) + batch_size - 1) // batch_size

    # Build prompt with or without context
    if context:
        system_prompt = build_translation_prompt(movie_title, context)
    else:
        system_prompt = f"""You are a professional subtitle translator specializing in English to Finnish translation.
You are translating subtitles for: {movie_title}

Guidelines:
- Translate naturally into Finnish, not word-for-word
- Use informal "sinä" for "you" unless context suggests formal
- Keep interjections natural in Finnish
- Keep translations concise to fit on screen
- Handle idioms appropriately for Finnish audience

Return ONLY the translated text, one subtitle per line, in the same order as input.
Use "---" as separator between subtitles."""

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
        task = progress.add_task(f"Translating", total=total_batches)

        for i in range(0, len(subs), batch_size):
            batch = subs[i : i + batch_size]

            # Prepare batch text with clear separators
            batch_texts = [sub.text.replace("\n", " ") for sub in batch]
            input_text = "\n---\n".join(batch_texts)

            # Add context about position in movie
            position_note = ""
            if i == 0:
                position_note = "(Beginning of movie)\n\n"
            elif i + batch_size >= len(subs):
                position_note = "(End of movie)\n\n"

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"{position_note}Translate to Finnish:\n\n{input_text}",
                        },
                    ],
                )

                translated_text = response.choices[0].message.content.strip()
                translations = translated_text.split("\n---\n")

                # Handle case where model doesn't use separator
                if len(translations) == 1 and len(batch) > 1:
                    # Try splitting by newlines
                    translations = [
                        t.strip() for t in translated_text.split("\n") if t.strip()
                    ]

                # Create translated subtitle items
                for j, sub in enumerate(batch):
                    new_sub = pysrt.SubRipItem(
                        index=sub.index,
                        start=sub.start,
                        end=sub.end,
                        text=translations[j].strip()
                        if j < len(translations)
                        else sub.text,
                    )
                    translated.append(new_sub)

            except Exception as e:
                console.print(
                    f"[red]Translation error in batch {i // batch_size + 1}: {e}[/red]"
                )
                # Keep original text on error
                for sub in batch:
                    translated.append(sub)

            progress.update(task, advance=1)

    return translated
