import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
import argparse

import pandas as pd
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from jsonschema import validate, ValidationError

try:
    from openai import OpenAI
except Exception as import_error:  # pragma: no cover
    OpenAI = None  # type: ignore


ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = ROOT / "prompts"
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
SCHEMA_PATH = ROOT / "schema" / "autoparts.schema.json"


def load_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_prompts() -> Dict[str, str]:
    system_prompt_path = PROMPTS_DIR / "system_prompt.txt"
    user_template_path = PROMPTS_DIR / "user_prompt_template.txt"
    return {
        "system": load_text_file(system_prompt_path),
        "user_template": load_text_file(user_template_path),
    }


def read_skus(csv_path: Path, limit: int) -> List[str]:
    df = pd.read_csv(csv_path, encoding="utf-8")
    if "Артикул" not in df.columns:
        raise ValueError("CSV must contain column 'Артикул'")
    skus = [str(v).strip() for v in df["Артикул"].dropna().tolist()]
    return skus[:limit]


def ensure_out_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sanitize_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped.strip("`")
        # If a language hint like ```json was used, split the first line
        if "\n" in stripped:
            first_newline = stripped.find("\n")
            maybe_lang = stripped[:first_newline].strip()
            if maybe_lang.lower() in {"json", "javascript", "js"}:
                stripped = stripped[first_newline + 1 :].strip()
    return stripped


def load_schema() -> Dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_and_normalize(result_obj: Dict[str, Any], sku: str) -> Dict[str, Any]:
    article = result_obj.get("Артикул") or sku
    name = result_obj.get("Наименование товара") or f"Артикул {article} — не найден"
    description = result_obj.get("Описание товара") or ""
    brand = result_obj.get("Марка") or ""
    models = result_obj.get("Модель")

    # Normalize models to a list of strings with at least one item
    normalized_models: List[str]
    if models is None:
        normalized_models = ["нет данных"]
    elif isinstance(models, list):
        normalized_models = [str(m).strip() for m in models if str(m).strip()]
        if not normalized_models:
            normalized_models = ["нет данных"]
    else:
        normalized_models = [str(models).strip() or "нет данных"]

    return {
        "Артикул": str(article),
        "Наименование товара": str(name),
        "Описание товара": str(description),
        "Марка": str(brand),
        "Модель": normalized_models[:6],
    }


SCHEMA: Dict[str, Any] = {}


def validate_schema(obj: Dict[str, Any]) -> Dict[str, Any]:
    global SCHEMA
    if not SCHEMA:
        SCHEMA = load_schema()
    try:
        validate(instance=obj, schema=SCHEMA)
        return obj
    except ValidationError as e:
        return {
            "Артикул": obj.get("Артикул") or "",
            "Наименование товара": obj.get("Наименование товара")
            or "Артикул {} — не найден".format(obj.get("Артикул", "")),
            "Описание товара": obj.get("Описание товара") or "",
            "Марка": obj.get("Марка") or "",
            "Модель": obj.get("Модель") or ["нет данных"],
            "schema_error": e.message,
        }


class OpenAIClient:
    def __init__(self, api_key: str, model: str) -> None:
        if OpenAI is None:
            raise RuntimeError(
                "openai package is not available. Please install dependencies."
            )
        self.client = OpenAI(api_key=api_key)
        self.model = model

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type(Exception),
    )
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        # Prefer the aggregated text helper if available
        text = getattr(response, "output_text", None)
        if isinstance(text, str) and text.strip():
            return text

        # Fallback: best-effort extraction from output structure
        try:
            outputs = getattr(response, "output", None) or []
            if outputs and isinstance(outputs, list):
                first = outputs[0]
                content = first.get("content") if isinstance(first, dict) else None
                if isinstance(content, list) and content:
                    part = content[0]
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        return str(part.get("text", "")).strip()
        except Exception:
            pass
        # Last resort: stringify the whole response
        return str(response)


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_excel(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        # create empty structure with expected columns
        rows = [
            {
                "Артикул": "",
                "Наименование товара": "",
                "Описание товара": "",
                "Марка": "",
                "Модель": [""],
            }
        ]
    df = pd.DataFrame(rows)
    # Join model list as comma-separated string for Excel readability
    if "Модель" in df.columns:
        df["Модель"] = df["Модель"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else str(v)
        )
    df.to_excel(path, index=False)


def write_markdown_table(path: Path, rows: List[Dict[str, Any]]) -> None:
    headers = ["Артикул", "Наименование товара", "Описание товара", "Марка", "Модель"]
    lines: List[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        models = row.get("Модель")
        models_str = ", ".join(models) if isinstance(models, list) else str(models)
        cells = [
            str(row.get("Артикул", "")),
            str(row.get("Наименование товара", "")),
            str(row.get("Описание товара", "")),
            str(row.get("Марка", "")),
            models_str,
        ]
        # escape pipe characters to not break Markdown table
        cells = [c.replace("|", "\|") for c in cells]
        lines.append("| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autoparts GPT runner")
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max number of SKUs to process (default: 50)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        help="OpenAI model name",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DATA_DIR / "skus.csv"),
        help="Path to input CSV with column 'Артикул'",
    )
    parser.add_argument(
        "--outdir",
        type=str,
        default=str(OUT_DIR),
        help="Directory to write outputs",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is not set. Create .env and set the key.", file=sys.stderr)
        sys.exit(1)

    csv_path = Path(args.input)
    out_dir = Path(args.outdir)
    ensure_out_dir(out_dir)

    prompts = read_prompts()
    system_prompt = prompts["system"]
    user_template = prompts["user_template"]

    skus = read_skus(csv_path, args.limit)
    if not skus:
        print("No SKUs found to process.")
        return

    client = OpenAIClient(api_key=api_key, model=args.model)

    results: List[Dict[str, Any]] = []
    for index, sku in enumerate(skus, start=1):
        user_prompt = user_template.format(sku=sku)
        try:
            raw_text = client.generate(system_prompt=system_prompt, user_prompt=user_prompt)
            raw_text = sanitize_json_text(raw_text)
            parsed = json.loads(raw_text)
        except Exception as gen_error:
            parsed = {
                "Артикул": sku,
                "Наименование товара": f"Артикул {sku} — не найден",
                "Описание товара": "",
                "Марка": "",
                "Модель": ["нет данных"],
                "error": str(gen_error),
            }

        normalized = validate_and_normalize(parsed, sku)
        validated = validate_schema(normalized)
        results.append(validated)

        # simple progress
        print(f"[{index}/{len(skus)}] {sku}")

    write_jsonl(out_dir / "results.jsonl", results)
    write_excel(out_dir / "results.xlsx", results)
    write_markdown_table(out_dir / "results.md", results)
    print(
        f"Done. Wrote: {out_dir / 'results.jsonl'}, {out_dir / 'results.xlsx'}, {out_dir / 'results.md'}"
    )


if __name__ == "__main__":
    main()

