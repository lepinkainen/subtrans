# Translation Process

This document describes the subtitle translation workflow in subtrans, including the two-pass architecture, parsing strategies, and quality validation.

## Overview: Two-Phase Workflow

```mermaid
flowchart TD
    Start([User runs subtrans]) --> Fetch[Fetch wanted movies from Bazarr]
    Fetch --> Select[Interactive movie selection]
    Select --> Phase1{Phase 1: Context Analysis}

    Phase1 --> |For each movie| Extract1[Extract subtitle]
    Extract1 --> Analyze[Analyze context with GPT-5<br/>Service tier: auto]
    Analyze --> Display[Display context JSON]
    Display --> Approve{User approves?}

    Approve --> |Yes| Track1[Track as approved]
    Approve --> |No| Skip1[Skip movie]
    Approve --> |Edit| Edit[Edit context with $EDITOR]
    Edit --> Display

    Track1 --> More1{More movies?}
    Skip1 --> More1
    More1 --> |Yes| Phase1
    More1 --> |No| Check{Any approved?}

    Check --> |No| End1([Exit])
    Check --> |Yes| Phase2{Phase 2: Translation}

    Phase2 --> |For each approved| Extract2[Load cached subtitle]
    Extract2 --> LoadCtx[Load cached context]
    LoadCtx --> Translate[Translate with GPT-5<br/>Service tier: flex]
    Translate --> Save[Save .fi.srt file]

    Save --> More2{More movies?}
    More2 --> |Yes| Phase2
    More2 --> |No| End2([Complete])

    style Phase1 fill:#e1f5ff
    style Phase2 fill:#ffe1e1
    style Analyze fill:#90caf9
    style Translate fill:#ef9a9a
```

## Pass 1: Context Analysis

```mermaid
flowchart TD
    Start([Start Context Analysis]) --> Find[Find subtitle source]
    Find --> Ext{External SRT?}

    Ext --> |Yes| LoadSRT[Load external .srt file]
    Ext --> |No| MKV{Embedded in MKV?}

    MKV --> |Yes| Cache{In cache?}
    Cache --> |Yes| LoadCache[Load from cache]
    Cache --> |No| Extract[Extract with mkvextract]
    Extract --> SaveCache[Save to cache]
    SaveCache --> Combine

    LoadSRT --> Combine[Combine all subtitle text]
    LoadCache --> Combine

    Combine --> CallAPI[Call GPT-5 Analysis API<br/>Model: gpt-5<br/>Service tier: auto]
    CallAPI --> Response{API Success?}

    Response --> |Yes| ParseJSON[Parse JSON response]
    Response --> |Quota Error| Exit1([Exit gracefully])
    Response --> |Other Error| Retry{Retries left?}

    Retry --> |Yes| CallAPI
    Retry --> |No| Fail([Use empty context])

    ParseJSON --> Extract2[Extract context:<br/>- Characters<br/>- Places<br/>- Terms<br/>- Genre/Tone/Formality<br/>- Style notes]

    Extract2 --> SaveCtx{save_context enabled?}
    SaveCtx --> |Yes| SaveJSON[Save to JSON file]
    SaveCtx --> |No| Return
    SaveJSON --> Return([Return TranslationContext])

    style CallAPI fill:#90caf9
    style Extract2 fill:#a5d6a7
```

## Pass 2: Batch Translation

```mermaid
flowchart TD
    Start([Start Translation]) --> BuildPrompt[Build translation prompt<br/>with context from Pass 1]
    BuildPrompt --> Batch[Split subtitles into batches<br/>Default: 50 per batch]

    Batch --> |For each batch| Format[Format batch with position markers<br/>Beginning/End of movie]
    Format --> CallAPI[Call GPT-5 Translation API<br/>Model: gpt-5<br/>Service tier: flex<br/>Timeout: 900s]

    CallAPI --> Response{API Success?}

    Response --> |Yes| Parse[Parse response]
    Response --> |Quota Error| Exit([Exit gracefully])
    Response --> |429 Resource Unavailable| Wait[Wait and retry<br/>Flex tier slower]
    Response --> |Other Error| Retry{Retries left?}

    Wait --> CallAPI
    Retry --> |Yes| CallAPI
    Retry --> |No| KeepOrig[Keep original text]

    Parse --> Parsed[Parsed translations]
    KeepOrig --> NextBatch

    Parsed --> Validate[Validate translations]
    Validate --> NextBatch{More batches?}

    NextBatch --> |Yes| Batch
    NextBatch --> |No| Return([Return translated subtitles])

    style CallAPI fill:#ef9a9a
    style Parse fill:#fff9c4
    style Validate fill:#c5e1a5
```

## Translation Response Parsing (Liberal Parser)

```mermaid
flowchart TD
    Start([Raw API response]) --> Check{Response empty?}

    Check --> |Yes| Error1[Error: Empty response]
    Check --> |No| S1[Strategy 1: Split by \\n[NEXT]\\n]

    S1 --> Count1{Count = expected?}
    Count1 --> |Yes| Validate
    Count1 --> |No, got 1| S2[Strategy 2: Split by [NEXT]]

    S2 --> Count2{Count = expected?}
    Count2 --> |Yes| Validate
    Count2 --> |No, got 1| S3[Strategy 3: Split by \\n---\\n]

    S3 --> Count3{Count = expected?}
    Count3 --> |Yes| Validate
    Count3 --> |No, got 1| S4[Strategy 4: Fallback<br/>Split by \\n, filter separators]

    S4 --> Filter[Filter with _is_likely_separator:<br/>- No word characters?<br/>- Repeated chars ^^^.^^^?<br/>- Known markers?]
    Filter --> Count4{Count = expected?}

    Count4 --> |Yes| Validate
    Count4 --> |No| Error2[Error: Count mismatch]

    Validate[Content Validation] --> |For each| CheckContent{Valid content?}
    CheckContent --> |Has word chars| Valid[Valid translation]
    CheckContent --> |Separator-like| Error3[Error: Invalid content]

    Valid --> AllValid{All valid?}
    AllValid --> |Yes| Success([Return translations])
    AllValid --> |No| CheckContent

    Error1 --> Fail([Raise ValueError])
    Error2 --> Fail
    Error3 --> Fail

    style S4 fill:#fff9c4
    style Filter fill:#c5e1a5
    style Validate fill:#90caf9
```

## Separator Detection (Pattern-Based)

```mermaid
flowchart TD
    Start([Check if text is separator]) --> Strip[Strip whitespace]

    Strip --> Check1{Empty or [NEXT]?}
    Check1 --> |Yes| IsSep([True: Is separator])
    Check1 --> |No| Check2{Has word chars<br/>^^[\\w]^^?}

    Check2 --> |No| IsSep
    Check2 --> |Yes| Check3{Repeated pattern<br/>^^^.^^^\\1^^^2,^^^$^^?}

    Check3 --> |Yes, e.g. ---<br/>***<br/>===<br/>+++| IsSep
    Check3 --> |No| NotSep([False: Is content])

    style Check2 fill:#c5e1a5
    style Check3 fill:#fff9c4
```

## Quality Validation (Optional)

```mermaid
flowchart TD
    Start([Original & Translated]) --> Calc[Calculate text similarity<br/>using difflib.SequenceMatcher]

    Calc --> Compare{Similarity >= threshold?}

    Compare --> |Yes| Warn[Warning: Too similar<br/>May not be translated]
    Compare --> |No| Pass[Pass validation]

    Warn --> Check{validate_translation enabled?}
    Pass --> Success([Continue])

    Check --> |Yes| Fail([Keep original text])
    Check --> |No| Success

    style Calc fill:#90caf9
    style Warn fill:#ffcc80
```

## Subtitle Source Priority

```mermaid
flowchart TD
    Start([Find English subtitle]) --> External{External SRT exists?}

    External --> |Yes| Patterns[Check patterns:<br/>*.en.srt<br/>*.EN.srt<br/>*.[Ee]ng*.srt<br/>*.[Ee]nglish*.srt]
    External --> |No| Embedded[Look for embedded MKV tracks]

    Patterns --> Found1{Found?}
    Found1 --> |Yes| Return1([Use external SRT])
    Found1 --> |No| Embedded

    Embedded --> MKVInfo[Run mkvmerge -J to get tracks]
    MKVInfo --> Filter[Filter:<br/>- Text subtitles only<br/>- Language: eng/en/english]

    Filter --> Found3{Found?}
    Found3 --> |Yes| ExtractTrack[Extract with mkvextract]
    Found3 --> |No| FirstText[Use first text track]

    FirstText --> Found4{Found?}
    Found4 --> |Yes| ExtractTrack
    Found4 --> |No| Error([Error: No subtitle found])

    ExtractTrack --> CacheCheck{In cache?}
    CacheCheck --> |Yes| Return2([Use cached])
    CacheCheck --> |No| Extract[Extract to cache]
    Extract --> Return2

    style Return1 fill:#a5d6a7
    style Return2 fill:#a5d6a7
```

## Cost Optimization: Hybrid Service Tiers

```mermaid
flowchart LR
    subgraph Pass1[Pass 1: Context Analysis]
        A1[GPT-5<br/>service_tier: auto] --> B1[Standard pricing<br/>Fast response]
        B1 --> C1[Interactive:<br/>User reviews context]
    end

    subgraph Pass2[Pass 2: Translation]
        A2[GPT-5<br/>service_tier: flex] --> B2[50% discount<br/>Can be slower]
        B2 --> C2[Batch processing:<br/>Runs unattended]
        C2 --> D2[Prompt caching:<br/>90% discount on cached tokens]
    end

    Pass1 --> Pass2

    style Pass1 fill:#e1f5ff
    style Pass2 fill:#ffe1e1
    style B1 fill:#90caf9
    style B2 fill:#ef9a9a
    style D2 fill:#c5e1a5
```

## Key Features

### Liberal Parsing ("Be liberal in what you accept")

- **Pattern-based separator detection** handles ANY separator format
- Only fails when translations are actually missing (count mismatch)
- Accepts: `---`, `***`, `===`, `+++`, `###`, custom patterns
- Strict validation: Each translation MUST contain word characters

### Cost Optimization

- **Pass 1 (auto tier)**: Fast, interactive context analysis with human review
- **Pass 2 (flex tier)**: 50% cost savings on unattended batch translation
- **Prompt caching**: 90% discount on cached tokens with flex tier

### Error Handling

- **Quota errors**: Exit gracefully, no partial writes
- **429 Resource Unavailable**: Automatic retry with longer timeout for flex tier
- **Parse failures**: Keep original text, continue processing
- **Network errors**: Retry with exponential backoff

### Quality Assurance

- **Context analysis**: Extract character names, places, terminology for consistency
- **Similarity check**: Warn if translation too similar to original (optional)
- **Content validation**: Ensure actual content, not separators
- **Count validation**: Verify correct number of translations received
