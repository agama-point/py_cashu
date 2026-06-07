from __future__ import annotations

from pathlib import Path
from typing import Callable

import qrcode
from PIL import Image, ImageDraw, ImageFont


class TokenPdfRenderer:
    def __init__(
        self,
        output_dir: Path,
        *,
        file_stamp_fn: Callable[[], str],
        log_fn: Callable[[str], None],
    ) -> None:
        self.output_dir = output_dir
        self.logo_path = output_dir / "logo.png"
        self._file_stamp = file_stamp_fn
        self._log = log_fn

    def create_multi_token_pdf(
        self,
        *,
        tokens: list[str],
        amount_per_token: int,
        splits: list[list[int]],
        created_stamp: str,
        common_label: str,
        mint_url: str,
    ) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = self._unique_pdf_path(self.output_dir / f"agama_cashu_{self._file_stamp()}.pdf")
        width, height = 2480, 3508
        margin = 100
        gutter = 36
        page = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(page)
        font_title = self._pdf_font(42)
        font_body = self._pdf_font(30)
        font_small = self._pdf_font(24)

        cell_w = (width - 2 * margin - gutter) // 2
        cell_h = (height - 2 * margin - 2 * gutter) // 3
        cells: list[tuple[int, int, int, int]] = []
        for row in range(3):
            for col in range(2):
                left = margin + col * (cell_w + gutter)
                top = margin + row * (cell_h + gutter)
                cells.append((left, top, left + cell_w, top + cell_h))

        for cell in cells:
            draw.rectangle(cell, outline=(190, 190, 190), width=3)

        for index, token in enumerate(tokens[:5], start=1):
            left, top, right, bottom = cells[index - 1]
            qr = self._make_pdf_qr_with_logo_space(token)
            qr_size = min(right - left - 90, bottom - top - 170)
            qr = qr.resize((qr_size, qr_size))
            draw.text((left + 34, top + 28), str(index), fill="black", font=font_title)
            draw.text(
                (left + 96, top + 38),
                self._pdf_caption(amount_per_token, splits[index - 1], common_label),
                fill=(30, 30, 30),
                font=font_small,
            )
            page.paste(qr, (left + (right - left - qr_size) // 2, top + 100))

        info_left, info_top, _, info_bottom = cells[5]
        info_lines = [
            "Agama Cashu multi-token batch",
            f"Created: {created_stamp}",
            f"Mint: {mint_url}",
            f"Token count: {len(tokens)}",
            f"Amount per token: {amount_per_token} sats",
            f"Total amount: {amount_per_token * len(tokens)} sats",
            f"Common label: {common_label or '-'}",
            "",
            "Proof structure:",
        ]
        for index, split in enumerate(splits, start=1):
            info_lines.append(f"{index}: {split} = {sum(split)}")
        info_lines.extend(
            [
                "",
                "Each QR is an independent serialized Cashu token.",
                "Redeem tokens into fresh proofs before relying on them.",
            ]
        )
        y = info_top + 40
        for line_index, line in enumerate(info_lines):
            font = font_body if line_index == 0 else font_small
            draw.text((info_left + 36, y), line, fill="black", font=font)
            y += 46 if line_index == 0 else 34
            if y > info_bottom - 40:
                break

        page.save(pdf_path, "PDF", resolution=300.0)
        return pdf_path

    def _make_pdf_qr_with_logo_space(self, token: str) -> Image.Image:
        qr_code = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            border=4,
            box_size=10,
        )
        qr_code.add_data(token)
        qr_code.make(fit=True)
        image = qr_code.make_image(fill_color="black", back_color="white").convert("RGB")

        module_count = len(qr_code.modules)
        box_size = int(getattr(qr_code, "box_size", 10) or 10)
        requested_modules = 20
        max_modules = max(8, module_count // 4)
        clear_modules = min(requested_modules, max_modules)
        clear_px = clear_modules * box_size
        center = image.size[0] // 2
        half = clear_px // 2
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (center - half, center - half, center + half, center + half),
            fill="white",
        )
        self._paste_pdf_qr_logo(image, center - half, center - half, clear_px)
        return image

    def _paste_pdf_qr_logo(self, image: Image.Image, left: int, top: int, size: int) -> None:
        if not self.logo_path.exists():
            return
        try:
            logo = Image.open(self.logo_path).convert("RGBA")
            logo = logo.resize((size, size), Image.Resampling.LANCZOS)
            image.paste(logo.convert("RGB"), (left, top), logo)
        except Exception as exc:
            self._log(f"Could not paste QR logo {self.logo_path}: {exc}")

    def _pdf_caption(self, amount: int, split: list[int], common_label: str) -> str:
        caption = f"{amount} sats | proofs {split}"
        if common_label:
            caption = f"{caption} | {common_label}"
        return caption[:92]

    def _pdf_font(self, size: int) -> ImageFont.ImageFont:
        for path in [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _unique_pdf_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 100):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"Could not find a free PDF filename near {path}.")
