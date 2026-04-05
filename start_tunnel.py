"""Start an ngrok tunnel to the Flask server and keep it alive."""

from pyngrok import ngrok

tunnel = ngrok.connect(5000, "http")
print(f"\n{'='*50}")
print(f"  PUBLIC URL: {tunnel.public_url}")
print(f"{'='*50}")
print(f"\n  Open this on your iPhone!")
print(f"  Keep this terminal open.\n  Press Ctrl+C to stop.\n")

ngrok_process = ngrok.get_ngrok_process()
ngrok_process.proc.wait()
