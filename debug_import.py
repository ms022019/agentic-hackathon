import sys
import os
import vertexai.generative_models

print(f"Python: {sys.version}")
print(f"VertexAI Path: {vertexai.generative_models.__file__}")

try:
    from vertexai.generative_models import GoogleSearchRetrieval
    print("SUCCESS: from vertexai.generative_models import GoogleSearchRetrieval")
except Exception as e:
    print(f"FAIL: from vertexai.generative_models import GoogleSearchRetrieval -> {e}")

try:
    from vertexai.preview.generative_models import GoogleSearchRetrieval
    print("SUCCESS: from vertexai.preview.generative_models import GoogleSearchRetrieval")
except Exception as e:
    print(f"FAIL: from vertexai.preview.generative_models import GoogleSearchRetrieval -> {e}")

try:
    from vertexai.generative_models._generative_models import GoogleSearchRetrieval
    print("SUCCESS: from vertexai.generative_models._generative_models import GoogleSearchRetrieval")
except Exception as e:
    print(f"FAIL: from vertexai.generative_models._generative_models import GoogleSearchRetrieval -> {e}")

try:
    import vertexai.generative_models._generative_models
    print("SUCCESS: import vertexai.generative_models._generative_models")
except Exception as e:
    print(f"FAIL: import vertexai.generative_models._generative_models -> {e}")

print("\n--- Listing site-packages/vertexai/generative_models ---")
try:
    d = os.path.dirname(vertexai.generative_models.__file__)
    print(os.listdir(d))
except:
    pass
