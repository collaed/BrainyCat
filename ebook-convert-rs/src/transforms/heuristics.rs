//! Heuristic processing — dehyphenation, paragraph detection, scene breaks.
//!
//! Equivalent to Calibre's heuristic processing in the conversion pipeline.

use anyhow::Result;
use regex::Regex;
use std::sync::LazyLock;

use crate::pipeline::document::OebDocument;

static RE_DEHYPHEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(\w)-\s*\n\s*(\w)").unwrap());
static RE_UNWRAP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"([a-z,;])\s*\n\s*([a-z])").unwrap());
static RE_SCENE_BREAK: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<p[^>]*>\s*(?:[*\-\u{2013}\u{2014}]\s*){3,}</p>").unwrap());

/// Apply heuristic processing to improve poorly formatted books.
pub fn process(doc: &mut OebDocument) -> Result<()> {
    for (_name, html) in doc.html_files.iter_mut() {
        *html = dehyphenate(html);
        *html = unwrap_lines(html);
        *html = detect_scene_breaks(html);
    }
    tracing::debug!("Applied heuristic processing");
    Ok(())
}

/// Remove soft hyphens and rejoin hyphenated words at line breaks.
/// "knowl-\nedge" → "knowledge"
fn dehyphenate(html: &str) -> String {
    let result = html.replace('\u{00AD}', "");
    RE_DEHYPHEN.replace_all(&result, "$1$2").to_string()
}

/// Unwrap lines that were hard-wrapped (common in PDF→text conversions).
/// Detects lines that end without sentence-ending punctuation and joins them.
fn unwrap_lines(html: &str) -> String {
    RE_UNWRAP.replace_all(html, "$1 $2").to_string()
}

/// Detect scene breaks (lines of *** or --- or blank lines between paragraphs)
/// and convert to proper <hr/> elements.
fn detect_scene_breaks(html: &str) -> String {
    RE_SCENE_BREAK.replace_all(html, "<hr class=\"scene-break\"/>").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dehyphenate() {
        assert_eq!(dehyphenate("knowl-\nedge"), "knowledge");
        assert_eq!(dehyphenate("well-known"), "well-known"); // Don't break real hyphens
    }

    #[test]
    fn test_scene_breaks() {
        let input = "<p>Text before</p><p>* * *</p><p>Text after</p>";
        let result = detect_scene_breaks(input);
        assert!(result.contains("<hr class=\"scene-break\"/>"));
    }
}
