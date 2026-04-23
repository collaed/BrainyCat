//! Image transform — rescale images for target device profile.

use anyhow::Result;

use crate::pipeline::document::OebDocument;

/// Maximum image dimensions per output profile.
struct Profile {
    max_width: u32,
    max_height: u32,
}

fn get_profile(name: &str) -> Profile {
    match name {
        "kindle" => Profile { max_width: 1264, max_height: 1680 },
        "kobo" => Profile { max_width: 1404, max_height: 1872 },
        "phone" => Profile { max_width: 1080, max_height: 1920 },
        "tablet" => Profile { max_width: 1620, max_height: 2160 },
        _ => Profile { max_width: 1600, max_height: 2400 }, // generic
    }
}

/// Rescale images that exceed the target profile dimensions.
pub fn rescale(doc: &mut OebDocument, profile_name: &str) -> Result<()> {
    let profile = get_profile(profile_name);
    let mut resized = 0;

    for (name, data) in doc.images.iter_mut() {
        let mime = doc.mime_map.get(name).map(|s| s.as_str()).unwrap_or("");
        if !mime.starts_with("image/") {
            continue;
        }

        // Try to decode and check dimensions
        match image::load_from_memory(data) {
            Ok(img) => {
                let (w, h) = (img.width(), img.height());
                if w > profile.max_width || h > profile.max_height {
                    let resized_img = img.resize(
                        profile.max_width,
                        profile.max_height,
                        image::imageops::FilterType::Lanczos3,
                    );

                    let mut buf = std::io::Cursor::new(Vec::new());
                    let format = match mime {
                        "image/png" => image::ImageFormat::Png,
                        "image/gif" => image::ImageFormat::Gif,
                        _ => image::ImageFormat::Jpeg,
                    };
                    if resized_img.write_to(&mut buf, format).is_ok() {
                        *data = buf.into_inner();
                        resized += 1;
                        tracing::debug!("Resized {name}: {w}×{h} → {}×{}", resized_img.width(), resized_img.height());
                    }
                }
            }
            Err(_) => {
                tracing::warn!("Could not decode image: {name}");
            }
        }
    }

    if resized > 0 {
        tracing::info!("Resized {resized} images for {profile_name} profile");
    }
    Ok(())
}
