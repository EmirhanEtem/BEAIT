"""Generate default app icons for Tauri desktop app."""

import os
from PIL import Image, ImageDraw

icons_dir = r"C:\Users\emoca\Desktop\FlMcp\apps\desktop\src-tauri\icons"
os.makedirs(icons_dir, exist_ok=True)

# Create high-res 512x512 icon
size = 512
img = Image.new("RGBA", (size, size), (18, 20, 26, 255))
draw = ImageDraw.Draw(img)

# Orange rounded box background
margin = 40
draw.rounded_rectangle([margin, margin, size - margin, size - margin], radius=80, fill=(255, 132, 0, 255))

# Inner styling - dark FL lettering representation
inner_margin = 100
draw.rectangle([inner_margin, inner_margin, inner_margin + 50, size - inner_margin], fill=(18, 20, 26, 255))
draw.rectangle([inner_margin, inner_margin, size - inner_margin - 60, inner_margin + 45], fill=(18, 20, 26, 255))
draw.rectangle([inner_margin, size // 2 - 20, size - inner_margin - 120, size // 2 + 25], fill=(18, 20, 26, 255))

# Save PNGs of required sizes
sizes = {
    "32x32.png": (32, 32),
    "128x128.png": (128, 128),
    "128x128@2x.png": (256, 256),
    "icon.png": (512, 512),
    "Square30x30Logo.png": (30, 30),
    "Square44x44Logo.png": (44, 44),
    "Square71x71Logo.png": (71, 71),
    "Square89x89Logo.png": (89, 89),
    "Square107x107Logo.png": (107, 107),
    "Square142x142Logo.png": (142, 142),
    "Square150x150Logo.png": (150, 150),
    "Square284x284Logo.png": (284, 284),
    "Square310x310Logo.png": (310, 310),
    "StoreLogo.png": (50, 50),
}

for name, s in sizes.items():
    resized = img.resize(s, Image.Resampling.LANCZOS)
    resized.save(os.path.join(icons_dir, name))

# Save multi-resolution icon.ico
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(os.path.join(icons_dir, "icon.ico"), format="ICO", sizes=ico_sizes)

print("Tauri icons generated successfully in:", icons_dir)

