//! Pipeline module — orchestrates Input → OEB → Transforms → Output.

pub mod document;
pub mod metadata;

use anyhow::{Context, Result};
use std::path::Path;

use crate::formats;
use crate::transforms;

/// Thread-local lenient mode flag. When set, format readers skip bad
/// records instead of aborting, producing degraded-but-readable output.
std::thread_local! {
    static LENIENT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

/// Check if lenient mode is active for the current conversion.
pub fn is_lenient() -> bool {
    LENIENT.with(|c| c.get())
}

/// Options controlling the conversion pipeline.
pub struct ConvertOptions {
    pub extra_css: Option<String>,
    pub base_font_size: f32,
    pub chapter_xpath: String,
    pub heuristics: bool,
    pub output_profile: String,
    /// When true, skip bad records/files instead of aborting.
    /// Produces degraded-but-readable output from malformed input.
    pub lenient: bool,
}

/// Main conversion entry point.
///
/// 1. Detect input format from extension
/// 2. Parse into OEB intermediate document
/// 3. Apply transforms (CSS flattening, chapter detection, etc.)
/// 4. Detect output format from extension
/// 5. Serialize to output format
pub fn convert(input: &Path, output: &Path, options: &ConvertOptions) -> Result<()> {
    // Input size limit: reject files > 500 MB to prevent memory exhaustion
    const MAX_INPUT_SIZE: u64 = 500 * 1024 * 1024;
    let file_size = std::fs::metadata(input)
        .with_context(|| format!("Cannot stat input file: {}", input.display()))?
        .len();
    if file_size > MAX_INPUT_SIZE {
        anyhow::bail!(
            "Input file is {} MB, exceeding the {} MB limit",
            file_size / (1024 * 1024),
            MAX_INPUT_SIZE / (1024 * 1024)
        );
    }
    let input_ext = input
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();
    let output_ext = output
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();

    tracing::info!("Converting {input_ext} → {output_ext}");

    // Activate lenient mode for this conversion
    LENIENT.with(|c| c.set(options.lenient));
    if options.lenient {
        tracing::info!("Lenient mode: will skip bad records instead of aborting");
    }

    // Step 1: Parse input into OEB document
    let mut doc = match input_ext.as_str() {
        "epub" | "kepub" => formats::epub::read(input)
            .with_context(|| format!("Failed to read EPUB: {}", input.display()))?,
        "html" | "htm" | "xhtml" => formats::html::read(input)
            .with_context(|| format!("Failed to read HTML: {}", input.display()))?,
        "txt" | "text" | "md" => formats::txt::read(input)
            .with_context(|| format!("Failed to read text: {}", input.display()))?,
        "mobi" | "azw" | "azw3" | "prc" => formats::mobi::read(input)
            .with_context(|| format!("Failed to read MOBI: {}", input.display()))?,
        "pdf" => formats::pdf::read(input)
            .with_context(|| format!("Failed to read PDF: {}", input.display()))?,
        "svg" => formats::svg::read(input)
            .with_context(|| format!("Failed to read SVG: {}", input.display()))?,
        "docx" | "docm" => formats::docx::read(input)
            .with_context(|| format!("Failed to read DOCX: {}", input.display()))?,
        _ => anyhow::bail!("Unsupported input format: {input_ext}"),
    };

    // Step 2: Apply transforms
    if options.heuristics {
        transforms::heuristics::process(&mut doc)?;
    }
    transforms::structure::detect_chapters(&mut doc, &options.chapter_xpath)?;
    transforms::css::flatten(&mut doc, options.base_font_size)?;
    if let Some(ref css) = options.extra_css {
        transforms::css::inject(&mut doc, css)?;
    }
    transforms::images::rescale(&mut doc, &options.output_profile)?;
    transforms::metadata::update(&mut doc)?;

    // Step 3: Serialize to output format via temp file + atomic rename.
    // Writing to a temp file in the same directory ensures:
    //   - No half-written output if the process crashes
    //   - No corruption of an existing file being overwritten
    //   - rename() is atomic on the same filesystem
    let temp_path = atomic_temp_path(output);
    let write_result = match output_ext.as_str() {
        "epub" | "kepub" => formats::epub::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write EPUB: {}", output.display())),
        "html" | "htm" => formats::html::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write HTML: {}", output.display())),
        "txt" | "text" => formats::txt::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write text: {}", output.display())),
        "mobi" | "azw" | "prc" => formats::mobi::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write MOBI: {}", output.display())),
        "pdf" => formats::pdf::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write PDF: {}", output.display())),
        "svg" => formats::svg::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write SVG: {}", output.display())),
        "docx" => formats::docx::write(&doc, &temp_path)
            .with_context(|| format!("Failed to write DOCX: {}", output.display())),
        _ => anyhow::bail!("Unsupported output format: {output_ext}"),
    };

    match write_result {
        Ok(()) => {
            std::fs::rename(&temp_path, output).with_context(|| {
                format!(
                    "Failed to rename temp file {} → {}",
                    temp_path.display(),
                    output.display()
                )
            })?;
        }
        Err(e) => {
            // Clean up temp file on failure
            let _ = std::fs::remove_file(&temp_path);
            return Err(e);
        }
    }

    Ok(())
}

/// Generate a temp file path in the same directory as `target` so that
/// `rename()` is guaranteed to be atomic (same filesystem).
fn atomic_temp_path(target: &Path) -> std::path::PathBuf {
    let dir = target.parent().unwrap_or(Path::new("."));
    let stem = target
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("output");
    let pid = std::process::id();
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    dir.join(format!(".{stem}.{pid}.{ts}.tmp"))
}
