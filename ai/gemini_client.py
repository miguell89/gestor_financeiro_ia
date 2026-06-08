import json
from pathlib import Path

from config.settings import settings


class GeminiClient:
    def __init__(self):
        self.enabled = bool(settings.GEMINI_API_KEY)
        self.model = None

        if self.enabled:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel(settings.GEMINI_MODEL)

    def _parse_json(self, text, fallback):
        cleaned = text.strip().replace("```json", "").replace("```", "").strip()

        if "{" in cleaned and "}" in cleaned:
            cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return fallback

    def generate_json(self, prompt, fallback):
        if not self.enabled:
            return fallback

        try:
            response = self.model.generate_content(prompt, request_options={"timeout": 8})
            return self._parse_json(response.text, fallback)
        except Exception:
            return fallback

    def generate_json_from_image(self, prompt, image_path, fallback):
        if not self.enabled:
            return fallback

        import google.generativeai as genai

        try:
            uploaded = genai.upload_file(path=str(Path(image_path)))
            response = self.model.generate_content([prompt, uploaded], request_options={"timeout": 10})
            return self._parse_json(response.text, fallback)
        except Exception:
            return fallback

    def generate_text(self, prompt, fallback):
        if not self.enabled:
            return fallback

        try:
            response = self.model.generate_content(prompt, request_options={"timeout": 8})
            return response.text.strip()
        except Exception:
            return fallback
