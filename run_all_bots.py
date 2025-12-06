"""
Run All Trading Bots

This script runs all bot strategies. Use this for cron jobs.
"""

import os
import subprocess
import sys

def run_bot(script_name: str):
    """Run a bot script"""
    print(f"\n{'='*60}")
    print(f"🚀 Running {script_name}...")
    print('='*60)
    
    try:
        result = subprocess.run(
            [sys.executable, f"bots/{script_name}"],
            capture_output=False,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Failed to run {script_name}: {e}")
        return False

def main():
    print("🏁 STARTING ALL TRADING BOTS")
    print(f"{'='*60}")
    
    bots = []
    
    # Check which bots are configured
    if os.environ.get('GEMINI_BOT_API_KEY') and os.environ.get('GEMINI_API_KEY'):
        bots.append('gemini_bot.py')
    else:
        print("⏭️  Skipping Gemini (not configured)")
    
    if os.environ.get('DEEPSEEK_BOT_API_KEY') and os.environ.get('DEEPSEEK_API_KEY'):
        bots.append('deepseek_bot.py')
    else:
        print("⏭️  Skipping DeepSeek (not configured)")
    
    if not bots:
        print("❌ No bots configured! Set environment variables.")
        return
    
    # Run each bot
    results = {}
    for bot in bots:
        success = run_bot(bot)
        results[bot] = '✅' if success else '❌'
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 SUMMARY")
    print('='*60)
    for bot, status in results.items():
        print(f"   {status} {bot}")
    
    print(f"\n🏁 All bots complete!")

if __name__ == '__main__':
    main()
