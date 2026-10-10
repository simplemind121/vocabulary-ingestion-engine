from __future__ import annotations

from typing import Any

from app.adapters.paddleocr import PaddleOcrAdapter, _package_version

_OCR_VERSION = "PP-OCRv4"


class _RapidEngine:
    """The classic PaddleOCR call shape over RapidOCR on ONNX Runtime."""

    def __init__(self, lang: str, ocr_version: str = _OCR_VERSION) -> None:
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
                "Rec.ocr_version": OCRVersion(ocr_version),
                "Det.ocr_version": OCRVersion(ocr_version),
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

    def __init__(
        self, *, lang: str = "ch", ocr_version: str = _OCR_VERSION, refine: bool = True
    ) -> None:
        super().__init__(
            engine=_RapidEngine(lang, ocr_version),
            lang=lang,
            english_engine=_RapidEngine("en", ocr_version) if refine and lang != "en" else None,
        )
        if ocr_version != _OCR_VERSION:
            self.name = f"rapidocr-{ocr_version.lower().removeprefix('pp-ocr')}"
        self.version = f"{_package_version('rapidocr')}+{ocr_version}"


def _warm_up() -> None:
    """Load every model and run one page so nothing is fetched at run time."""
    import fitz

    from app.adapters.ocr_base import OcrPageInput

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "Thevocabularyengineiswarmingup", fontsize=20)
    image = OcrPageInput(
        page_number=1, image_bytes=page.get_pixmap(dpi=150, alpha=False).tobytes("png")
    )
    for adapter in (
        RapidOcrAdapter(lang="ch"),
        RapidOcrAdapter(lang="ch", ocr_version="PP-OCRv5", refine=False),
    ):
        if not adapter.extract_page(image).blocks:
            raise RuntimeError(f"{adapter.name} read nothing during warm-up")


if __name__ == "__main__":
    _warm_up()
