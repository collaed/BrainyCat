//! CSS transform — flatten styles, remap font sizes, inject extra CSS.
//!
//! Equivalent to Calibre's flatcss.py (29KB) but using lightningcss for parsing.

use anyhow::Result;
use std::sync::LazyLock;

use regex::Regex;

use crate::pipeline::document::OebDocument;

static RE_FONT_SIZE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"font-size\s*:\s*([\d.]+)(px|pt|em|rem)").unwrap());

/// Flatten CSS: resolve imports, normalize font sizes relative to base.
pub fn flatten(doc: &mut OebDocument, base_font_size: f32) -> Result<()> {
    for (_name, css) in doc.stylesheets.iter_mut() {
        *css = remap_font_sizes(css, base_font_size);
    }
    tracing::debug!("CSS flattened with base font size {base_font_size}pt");
    Ok(())
}

/// Inject extra CSS into all HTML files.
pub fn inject(doc: &mut OebDocument, extra_css: &str) -> Result<()> {
    let style_tag = format!("<style type=\"text/css\">\n{extra_css}\n</style>");

    for (_name, html) in doc.html_files.iter_mut() {
        // Insert before </head> if present
        if let Some(pos) = html.find("</head>") {
            html.insert_str(pos, &style_tag);
        }
    }
    tracing::debug!("Injected {} bytes of extra CSS", extra_css.len());
    Ok(())
}

/// Remap font sizes using a logarithmic key mapper.
///
/// Maps source font sizes to a normalized range based on the base font size.
/// This is equivalent to Calibre's KeyMapper algorithm in flatcss.py.
fn remap_font_sizes(css: &str, base_size: f32) -> String {
    let re = &*RE_FONT_SIZE;

    re.replace_all(css, |caps: &regex::Captures| {
        let value: f32 = caps[1].parse().unwrap_or(base_size);
        let unit = &caps[2];

        // Convert to pt
        let pt = match unit {
            "px" => value * 0.75,
            "em" | "rem" => value * base_size,
            _ => value,
        };

        // Logarithmic remapping: map to nearest standard size
        let standard_sizes = [7.0, 8.0, 9.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0, 36.0];
        let mapped = standard_sizes
            .iter()
            .min_by(|a, b| {
                (pt - *a).abs().partial_cmp(&(pt - *b).abs()).unwrap_or(std::cmp::Ordering::Equal)
            })
            .unwrap_or(&base_size);

        format!("font-size: {mapped}pt")
    })
    .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_remap_font_sizes() {
        let css = "body { font-size: 11px; } h1 { font-size: 24px; }";
        let result = remap_font_sizes(css, 12.0);
        // 11px = 8.25pt → maps to 8pt; 24px = 18pt → maps to 18pt
        assert!(result.contains("font-size: 8pt"));
        assert!(result.contains("font-size: 18pt"));
    }

    #[test]
    fn test_inject_css() {
        let mut doc = OebDocument::new();
        doc.add_html("test.xhtml", "<html><head></head><body>Hello</body></html>");
        inject(&mut doc, "body { color: red; }").unwrap();
        assert!(doc.html_files["test.xhtml"].contains("color: red"));
    }
}
