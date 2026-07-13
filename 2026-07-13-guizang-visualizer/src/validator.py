import json
import logging
from dataclasses import asdict
from io import BytesIO
from typing import Any, Dict, List, Optional

from PIL import Image, ImageChops
import pytesseract
from openai import OpenAI

from ..core.models import QAReport, IllustrationRequest, IllustrationResult
from ..tools import emit_event

logger = logging.getLogger(__name__)


class ImageValidator:
    """
    Executes the QA checklist against a generated image and decides whether
    automatic regeneration is required.
    """

    _ASPECT_RATIOS = {
        "slide": (16, 9),
        "article": (4, 3),
        "social_card": (1, 1),
    }

    def __init__(self, runtime_config: Any) -> None:
        """
        Initialise the validator with runtime configuration.
        """
        self._config = runtime_config
        self._llm_client = OpenAI(api_key=self._config.llm_api_key)
        self._max_regen_attempts = 2

    def _check_aspect_ratio(self, img: Image.Image, target_use: str) -> Optional[str]:
        """
        Verify that the image aspect ratio matches the expected ratio for the target use.
        Returns an error message if the check fails, otherwise None.
        """
        if target_use not in self._ASPECT_RATIOS:
            return f"Unsupported target_use '{target_use}' for aspect‑ratio check"
        expected_w, expected_h = self._ASPECT_RATIOS[target_use]
        width, height = img.size
        # Compute ratio as a reduced fraction
        actual_ratio = width / height
        expected_ratio = expected_w / expected_h
        if abs(actual_ratio - expected_ratio) > 0.05:  # allow 5 % tolerance
            return (
                f"Aspect ratio {width}:{height} ({actual_ratio:.2f}) does not match "
                f"expected {expected_w}:{expected_h} ({expected_ratio:.2f})"
            )
        return None

    def _run_ocr(self, img: Image.Image) -> str:
        """
        Run OCR on the image and return extracted text.
        """
        try:
            text = pytesseract.image_to_string(img, lang="chi_sim")
            return text.strip()
        except Exception as exc:  # pragma: no cover
            logger.warning("OCR failed: %s", exc)
            return ""

    def _llm_review(
        self,
        ocr_text: str,
        metadata: Dict[str, Any],
        prompt_used: str,
    ) -> QAReport:
        """
        Send a lightweight review request to the secondary LLM.
        The LLM is expected to return a JSON object with the QAReport fields.
        """
        system_msg = (
            "You are a strict reviewer for Guizang‑style visualizations. "
            "Assess the provided OCR text and metadata against the prompt that generated the image. "
            "Return a JSON object with the keys: passed (bool), failed_checks (list of strings), "
            "details (object), retryable (bool)."
        )
        user_msg = json.dumps(
            {
                "prompt": prompt_used,
                "ocr_text": ocr_text,
                "metadata": metadata,
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            response = self._llm_client.chat.completions.create(
                model=self._config.llm_model_name,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            report_dict = json.loads(content)
            return QAReport(
                passed=bool(report_dict.get("passed", False)),
                failed_checks=report_dict.get("failed_checks", []),
                details=report_dict.get("details", {}),
                retryable=bool(report_dict.get("retryable", False)),
            )
        except Exception as exc:  # pragma: no cover
            logger.error("LLM review failed: %s", exc)
            return QAReport(
                passed=False,
                failed_checks=["llm_review_error"],
                details={"error": str(exc)},
                retryable=False,
            )

    def run_checks(self, image: bytes, metadata: Dict[str, Any]) -> QAReport:
        """
        Execute the full QA checklist and return a QAReport.
        """
        emit_event("validator:start", image_len=len(image), metadata=metadata)
        try:
            img = Image.open(BytesIO(image)).convert("RGB")
        except Exception as exc:  # pragma: no cover
            logger.error("Unable to open image: %s", exc)
            report = QAReport(
                passed=False,
                failed_checks=["invalid_image"],
                details={"error": str(exc)},
                retryable=False,
            )
            emit_event("validator:complete", report=asdict(report))
            return report

        failed: List[str] = []

        # 1. Basic sanity checks
        if img.width == 0 or img.height == 0:
            failed.append("zero_dimensions")
        if img.getbbox() is None:
            failed.append("empty_image")

        # 2. Aspect‑ratio validation
        target_use = metadata.get("target_use")
        if target_use:
            ar_error = self._check_aspect_ratio(img, target_use)
            if ar_error:
                failed.append("aspect_ratio_mismatch")
        else:
            failed.append("missing_target_use")

        # 3. OCR extraction
        ocr_text = self._run_ocr(img)

        # 4. Secondary LLM review
        llm_report = self._llm_review(ocr_text, metadata, metadata.get("prompt_used", ""))
        if not llm_report.passed:
            failed.extend(llm_report.failed_checks)

        # Consolidate results
        overall_pass = not failed and llm_report.passed
        report = QAReport(
            passed=overall_pass,
            failed_checks=failed,
            details={"ocr_text": ocr_text, **llm_report.details},
            retryable=llm_report.retryable if not overall_pass else False,
        )
        emit_event("validator:complete", report=asdict(report))
        return report

    def _regenerate_image(
        self,
        request: IllustrationRequest,
        prompt: str,
    ) -> IllustrationResult:
        """
        Internal helper that calls the image model endpoint directly.
        """
        client = OpenAI(api_key=self._config.image_model_api_key)
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=self._size_for_use(request.target_use),
                response_format="b64_json",
                n=1,
            )
            b64_data = response.data[0].b64_json
            image_bytes = BytesIO()
            image_bytes.write(base64.b64decode(b64_data))
            image_bytes.seek(0)
            result = IllustrationResult(
                request_id=request.request_id,
                image_bytes=image_bytes.read(),
                prompt_used=prompt,
                qa_report=QAReport(passed=False, failed_checks=[], details={}, retryable=False),
                timestamp=self._now(),
            )
            return result
        except Exception as exc:  # pragma: no cover
            logger.error("Image regeneration failed: %s", exc)
            raise

    def _size_for_use(self, target_use: str) -> str:
        """
        Map target_use to a DALL·E size string.
        """
        mapping = {
            "slide": "1024x576",
            "article": "1024x768",
            "social_card": "1024x1024",
        }
        return mapping.get(target_use, "1024x1024")

    def _now(self):
        """
        Return the current UTC datetime.
        """
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    def auto_regenerate(self, report: QAReport, request: IllustrationRequest) -> IllustrationResult:
        """
        Decide whether to retry image generation based on the QAReport.
        If retryable, attempts regeneration up to the configured limit.
        """
        emit_event("validator:auto_regenerate:start", request_id=request.request_id, retryable=report.retryable)
        if not report.retryable:
            raise ValueError("QAReport marked as non‑retryable; cannot auto‑regenerate")

        attempts = 0
        last_error: Optional[Exception] = None
        while attempts < self._max_regen_attempts:
            attempts += 1
            try:
                # Re‑build the prompt using the same logic as the engine would.
                # The engine's PromptBuilder is not directly accessible here; we assume
                # the original prompt is stored in request metadata.
                prompt = request.custom_accent or "Generate a Guizang‑style illustration"
                result = self._regenerate_image(request, prompt)
                # Run checks again on the newly generated image
                new_report = self.run_checks(result.image_bytes, {"target_use": request.target_use, "prompt_used": prompt})
                if new_report.passed:
                    result.qa_report = new_report
                    emit_event(
                        "validator:auto_regenerate:success",
                        request_id=request.request_id,
                        attempts=attempts,
                    )
                    return result
                if not new_report.retryable:
                    raise ValueError("Regenerated image failed QA and is not retryable")
            except Exception as exc:  # pragma: no cover
                last_error = exc
                logger.warning("Regeneration attempt %d failed: %s", attempts, exc)

        emit_event(
            "validator:auto_regenerate:failed",
            request_id=request.request_id,
            attempts=attempts,
            error=str(last_error) if last_error else "unknown",
        )
        raise RuntimeError(f"Failed to regenerate a valid image after {self._max_regen_attempts} attempts")