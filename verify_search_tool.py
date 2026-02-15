import vertexai.generative_models

print("Checking for GoogleSearch tool...")
if hasattr(vertexai.generative_models, "GoogleSearch"):
    print("GoogleSearch found!")
else:
    print("GoogleSearch NOT found directly.")

import vertexai.preview.generative_models
if hasattr(vertexai.preview.generative_models, "GoogleSearch"):
    print("GoogleSearch found in preview!")
else:
    print("GoogleSearch NOT found in preview.")
    
try:
    from vertexai.generative_models import Tool
    t = Tool(google_search=vertexai.generative_models.GoogleSearch())
    print("Successfully instantiated Tool(google_search=...)")
except Exception as e:
    print(f"Instantiation failed: {e}")
