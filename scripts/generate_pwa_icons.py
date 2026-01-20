"""
Generate PWA icons from the armada_logo.png
Run: python scripts/generate_pwa_icons.py
Requires: pip install Pillow
"""
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Please install Pillow: pip install Pillow")
    exit(1)

# Paths
BASE_DIR = Path(__file__).parent.parent
LOGO_PATH = BASE_DIR / "app" / "static" / "armada_logo.png"
ICONS_DIR = BASE_DIR / "app" / "static" / "icons"

# Icon sizes for PWA
SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

def generate_icons():
    """Generate PWA icons in various sizes."""
    # Ensure icons directory exists
    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # Load the source logo
    if not LOGO_PATH.exists():
        print(f"Error: Logo not found at {LOGO_PATH}")
        return

    with Image.open(LOGO_PATH) as img:
        # Convert to RGBA if necessary
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        for size in SIZES:
            # Resize with high quality
            resized = img.resize((size, size), Image.Resampling.LANCZOS)

            # Save the icon
            output_path = ICONS_DIR / f"icon-{size}.png"
            resized.save(output_path, 'PNG', optimize=True)
            print(f"Created: {output_path}")

    print(f"\nAll icons generated in {ICONS_DIR}")
    print("PWA is now ready to install!")

if __name__ == "__main__":
    generate_icons()
