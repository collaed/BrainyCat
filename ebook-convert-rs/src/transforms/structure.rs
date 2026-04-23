//! Structure detection — find chapters, generate TOC.
//!
//! Equivalent to Calibre's structure.py transform.

use anyhow::Result;
use regex::Regex;
use std::sync::LazyLock;

use crate::pipeline::document::{OebDocument, TocEntry};

static RE_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<h([1-3])[^>]*>(.*?)</h[1-3]>").unwrap());
static RE_STRIP_TAGS: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").unwrap());
static RE_SPLIT_HEADING: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)<h[12][^>]*>").unwrap());

/// Detect chapter boundaries and build TOC.
pub fn detect_chapters(doc: &mut OebDocument, _xpath: &str) -> Result<()> {
    let heading_re = &*RE_HEADING;
    let strip_tags = &*RE_STRIP_TAGS;
    let mut toc = Vec::new();

    for name in &doc.spine {
        if let Some(html) = doc.html_files.get(name) {
            for cap in heading_re.captures_iter(html) {
                let level: u8 = cap[1].parse().unwrap_or(1);
                let raw_title = &cap[2];
                let title = strip_tags.replace_all(raw_title, "").trim().to_string();

                if !title.is_empty() && level <= 2 {
                    toc.push(TocEntry {
                        title,
                        href: name.clone(),
                        children: Vec::new(),
                    });
                }
            }
        }
    }

    if !toc.is_empty() {
        doc.toc = toc;
        tracing::debug!("Detected {} TOC entries from headings", doc.toc.len());
    }
    Ok(())
}

/// Split a single large HTML file into per-chapter files at heading boundaries.
pub fn split_at_chapters(doc: &mut OebDocument) -> Result<()> {
    let heading_re = &*RE_SPLIT_HEADING;

    let spine_clone = doc.spine.clone();
    for name in &spine_clone {
        let html = match doc.html_files.get(name) {
            Some(h) => h.clone(),
            None => continue,
        };

        let positions: Vec<usize> = heading_re.find_iter(&html).map(|m| m.start()).collect();
        if positions.len() <= 1 {
            continue; // Already one chapter or no headings
        }

        // Extract head content
        let head_end = html.find("</head>").unwrap_or(0);
        let head = if head_end > 0 {
            &html[..head_end + 7]
        } else {
            r#"<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter</title></head>"#
        };

        let body_start = html.find("<body").unwrap_or(0);
        let body_end = html.rfind("</body>").unwrap_or(html.len());

        // Split body at heading positions
        let body = &html[body_start..body_end];
        let mut new_files = Vec::new();

        for (i, &pos) in positions.iter().enumerate() {
            let relative_pos = pos - body_start;
            let end = if i + 1 < positions.len() {
                positions[i + 1] - body_start
            } else {
                body.len()
            };

            let chunk = &body[relative_pos..end];
            let new_name = format!("ch_{:03}.xhtml", i);
            let new_html = format!("{head}\n<body>\n{chunk}\n</body>\n</html>");

            new_files.push((new_name, new_html));
        }

        // Replace original file with split files
        doc.html_files.remove(name);
        doc.spine.retain(|n| n != name);

        let insert_pos = doc.spine.len(); // append at end
        for (new_name, new_html) in new_files {
            doc.add_html(&new_name, new_html);
        }
    }

    tracing::debug!("Split into {} spine items", doc.spine.len());
    Ok(())
}
