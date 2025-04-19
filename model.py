import os
import uuid
from io import BytesIO
from PIL import Image
from google.genai import types
import requests

class Model:
    def __init__(self, client, api_key):
        self.client = client
        self.api_key = api_key

    def prepare_generation_contents(self, prompt_text, image_file=None):
        if image_file:
            pil_image = Image.open(image_file.stream)
            img_buffer = BytesIO()
            pil_image.save(img_buffer, format="PNG")
            img_bytes = img_buffer.getvalue()

            contents = [
                types.Content(role="user", parts=[
                    types.Part(text=prompt_text),
                    types.Part(inline_data=types.Blob(mime_type="image/png", data=img_bytes))
                ])
            ]
        else:
            contents = [
                types.Content(role="user", parts=[
                    types.Part(text=prompt_text)
                ])
            ]
        return contents

    def generate_image_from_contents(self, contents):
        try:
            return self.client.models.generate_content(
                model="gemini-2.0-flash-exp-image-generation",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=['Text', 'Image']
                )
            )
        except Exception as e:
            print(f"[Gemini Error] {e}")
            return None

    def extract_image_from_response(self, response, output_dir='static/generated'):
        if not response or not hasattr(response, 'candidates'):
            return None
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                img = Image.open(BytesIO(part.inline_data.data))
                fname = f"{uuid.uuid4().hex}.png"
                out_path = os.path.join(output_dir, fname)
                img.save(out_path)
                return fname
        return None

    def extract_query_from_image(self, image_path):
        with Image.open(image_path) as gen_image:
            detect_prompt = (
                "Mô tả ngắn gọn về sản phẩm quần áo trong ảnh, chỉ ra (hình dáng, màu sắc, các đặc điểm quan trọng) để tôi có thể tìm kiếm trên sàn thương mại điện tử bằng tiếng anh. Chỉ trả về mô tả sản phẩm, không cần giới thiệu hoặc lời khẳng định."
            )

            detect_resp = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[detect_prompt, gen_image],
                config=types.GenerateContentConfig(response_modalities=['Text'])
            )
            for part in detect_resp.candidates[0].content.parts:
                if part.text:
                    return part.text
        return ""

    def outfit_recommend(self, image_path):
        outfit_query = self.extract_query_from_image(image_path)
        prompt = f"Đưa tôi chỉ 1 (keyword) gợi ý outfit phù hợp để mặc với {outfit_query} để tôi có thể tìm thêm sản phẩm tương ứng, không cần nói chi tiết lý do đâu, chỉ cần keyword đầy đủ để tôi tìm kiếm dễ dàng trên các nền tảng thương mại bằng tiếng anh, không cần giới thiệu hoặc lời khẳng định."
        response = self.client.models.generate_content(
            model="gemini-2.5-pro-exp-03-25",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=['text']
            )
        )

        outfit_suggestion = ""
        for part in response.text.strip().split("\n"):
            if part:
                outfit_suggestion += part + ", "

        outfit_suggestion = outfit_suggestion.replace("*", "").strip().rstrip(",")
        if not outfit_suggestion:
            return None
        return outfit_suggestion

    def search_data(self, query):
        params = {
            "q": query,
            "tbm": "shop",
            "num": 10,
            "api_key": self.api_key
        }

        try:
            response = requests.get("https://serpapi.com/search", params=params)
            results = response.json()
            items = results.get("shopping_results", [])
        except Exception:
            items = []

        detailed_items = []
        for item in items[:10]:
            detailed_items.append({
                "title": item.get("title"),
                "price": item.get("price"),
                "source": item.get("source"),
                "link": item.get("product_link"),
                "thumbnail": item.get("thumbnail")
            })

        return detailed_items

    def try_on(self,person_path, outfit_path, output_dir='static/tryon'):
        try:
            with Image.open(person_path) as person_img, Image.open(outfit_path) as outfit_img:
                person_buffer = BytesIO()
                outfit_buffer = BytesIO()
                person_img.save(person_buffer, format="PNG")
                outfit_img.save(outfit_buffer, format="PNG")
                person_bytes = person_buffer.getvalue()
                outfit_bytes = outfit_buffer.getvalue()

            prompt_text = "Hãy thay trang phục trong ảnh thứ hai (outfit) vào người trong ảnh đầu tiên. Giữ nguyên tư thế, khuôn mặt và đặc điểm cơ thể của người trong ảnh. Kết quả nên là một bức ảnh thực tế thể hiện người đang mặc bộ trang phục từ ảnh thứ hai."

            contents = [
                types.Content(role="user", parts=[
                    types.Part(text=prompt_text),
                    types.Part(inline_data=types.Blob(mime_type="image/png", data=person_bytes)),
                    types.Part(inline_data=types.Blob(mime_type="image/png", data=outfit_bytes))
                ])
            ]
            response = self.generate_image_from_contents(contents)
            result_filename = self.extract_image_from_response(response, output_dir)
            return os.path.join(output_dir, result_filename) if result_filename else None
        except Exception as e:
            print(f"[Try-on Error] {e}")
            return None