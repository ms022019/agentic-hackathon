import vertexai
import vertexai.generative_models
import vertexai.preview.generative_models

print(f"Vertex AI Version: {vertexai.__version__}")

print("\n--- vertexai.generative_models dir ---")
for x in dir(vertexai.generative_models):
    if "Google" in x or "Search" in x or "Tool" in x:
        print(x)

print("\n--- vertexai.preview.generative_models dir ---")
for x in dir(vertexai.preview.generative_models):
    if "Google" in x or "Search" in x or "Tool" in x:
        print(x)
