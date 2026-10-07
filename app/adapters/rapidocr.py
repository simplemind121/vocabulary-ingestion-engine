from __future__ import annotations

from typing import Any

from app.adapters.paddleocr import PaddleOcrAdapter, _package_version

_OCR_VERSION = "PP-OCRv4"


class _RapidEngine:
    """The classic PaddleOCR call shape over RapidOCR on ONNX Runtime."""

    def __init__(self, lang: str) -> None:
        try:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import LangRec, OCRVersion
        except ImportError as exc:
            raise RuntimeError(
                "RapidOCR is not installed; install the OCR runtime before selecting rapidocr"
            ) from exc
        self._engine = RapidOCR(
            params={
                "Rec.lang_type": LangRec(lang),
                "Rec.ocr_version": OCRVersion(_OCR_VERSION),
                "Det.ocr_version": OCRVersion(_OCR_VERSION),
                "Global.log_level": "error",
            }
        )

    def ocr(self, image: Any, det: bool = True, cls: bool = False) -> list:
        if det:
            output = self._engine(image, use_cls=False)
            if output.boxes is None:
                return [[]]
            return [
                [
                    [box.tolist(), (text, float(score))]
                    for box, text, score in zip(
                        output.boxes, output.txts, output.scores, strict=True
                    )
                ]
            ]
        output = self._engine(image, use_det=False, use_cls=False)
        if not output.txts:
            return [[("", 0.0)]]
        return [[(output.txts[0], float(output.scores[0]))]]


class RapidOcrAdapter(PaddleOcrAdapter):
    """PP-OCR models run through ONNX Runtime.

    Same models and the same line handling as the PaddleOCR adapter, without
    the PaddlePaddle runtime: about a quarter of the memory and twice the
    speed on CPU, which is what lets it share a small host with the stack.
    """

    name = "rapidocr"

    def __init__(self, *, lang: str = "ch") -> None:
        super().__init__(
            engine=_RapidEngine(lang),
            lang=lang,
            english_engine=_RapidEngine("en") if lang != "en" else None,
        )
        self.version = f"{_package_version('rapidocr')}+{_OCR_VERSION}"
