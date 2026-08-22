#!/usr/bin/env python3
"""
setup_parser_profiles.py
═══════════════════════════════════════════════════════════════

ติดตั้ง Default Parser Profiles สำหรับการใช้งานครั้งแรก

ใช้งาน:
  python tools/setup_parser_profiles.py

หรือจากที่ root ของ V5:
  python tools/setup_parser_profiles.py

─────────────────────────────────────────────────────────────
เมื่อรันสคริปต์นี้ มันจะ:
  1. ✓ Copy default_profiles.json ไป ~/konica_parser_user_profiles.json
  2. ✓ แสดงรายการ Profiles ที่ได้รับ
  3. ✓ พร้อมใช้ check_parser.py ทันที
═══════════════════════════════════════════════════════════════
"""

import json
import sys
from pathlib import Path


def setup_profiles():
    """Setup default parser profiles to user home directory"""
    
    # Paths
    script_dir = Path(__file__).parent
    default_profiles_path = script_dir / "default_profiles.json"
    user_profiles_path = Path.home() / "konica_parser_user_profiles.json"
    
    print("═" * 70)
    print("  Parser Profiles Setup")
    print("═" * 70)
    print()
    
    # Check if default profiles exists
    if not default_profiles_path.exists():
        print(f"❌ Error: Default profiles not found at:")
        print(f"   {default_profiles_path}")
        print()
        print("   Make sure you're running from the correct directory:")
        print("   python tools/setup_parser_profiles.py")
        return False
    
    # Check if user profiles already exists
    if user_profiles_path.exists():
        print(f"ℹ️  User profiles already exist at:")
        print(f"   {user_profiles_path}")
        print()
        response = input("  Overwrite existing profiles? (y/N): ").strip().lower()
        if response != 'y':
            print("  Cancelled. No changes made.")
            return False
        print()
    
    # Copy default to home
    try:
        default_data = json.loads(default_profiles_path.read_text(encoding="utf-8"))
        user_profiles_path.write_text(
            json.dumps(default_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"✓ Profiles copied to: {user_profiles_path}")
        print()
        
        # Display loaded profiles
        print("Loaded Profiles:")
        print("─" * 70)
        for profile in default_data.get("profiles", []):
            slot = profile.get("slot", "?")
            name = profile.get("name", "Unknown")
            models = profile.get("models", "")
            types = profile.get("types", [])
            
            # Display
            status = "✓" if models else "·"
            types_str = ", ".join(types) if types else "(empty)"
            models_str = models if models else "(unused)"
            
            print(f"  {status} [{slot:2d}] {name:30} | {models_str:30} | {types_str}")
        
        print("─" * 70)
        print()
        print("✓ Setup Complete!")
        print()
        print("Next steps:")
        print("  1. Run: python tools/check_parser.py")
        print("  2. Test with sample files")
        print("  3. Customize profiles as needed")
        print()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = setup_profiles()
    sys.exit(0 if success else 1)
