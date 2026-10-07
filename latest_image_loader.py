import os
import math
import time
import logging
import numpy as np
import torch
from PIL import Image, ImageOps
import folder_paths

# Live node instances by execution id, so the refresh route can find each node's chain.
_NODES = {}


class LatestImageLoader:
    """Loads a selected starter image, then the newest matching image from a folder on later runs.

    Intended for iterative editing: each run loads the result of the previous run, so the
    user can keep editing the latest image. Changing the starter image (or using
    "start from selected") begins a new chain.
    """

    SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif")
    MODES = ("continue", "start from selected")

    def __init__(self):
        # Starter image the current chain was started from, and when it started.
        # Only outputs written after chain_start count as part of the chain.
        self.chain_starter = None
        self.chain_start = 0.0
        self.folder_path = ""
        self.filename_prefix = ""
        self.max_megapixels = 0.0
        self.size_multiple = 16

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        if hasattr(folder_paths, "filter_files_content_types"):
            files = folder_paths.filter_files_content_types(files, ["image"])
        return {
            "required": {
                "image": (sorted(files), {"image_upload": True}),
                "folder_path": ("STRING", {"default": folder_paths.get_output_directory(), "multiline": False}),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "Same prefix as your Save Image node (may include a subfolder, e.g. 'edits/img'). "
                               "Only matching files are loaded. Leave empty to match any image in the folder.",
                }),
                "mode": (cls.MODES, {
                    "default": "continue",
                    "tooltip": "continue: load the newest edit in the chain. "
                               "start from selected: always load the starter image and begin a new chain.",
                }),
            },
            "optional": {
                "max_megapixels": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 100.0, "step": 0.05,
                    "tooltip": "Shrink images larger than this (e.g. 1.0 for about 1024x1024) before editing. "
                               "Images already within the limit are left alone, so edits don't keep shrinking. "
                               "0 = off.",
                }),
                "size_multiple": ("INT", {
                    "default": 16, "min": 1, "max": 128,
                    "tooltip": "When downscaling is on, round width and height down to a multiple of this "
                               "(many models need multiples of 8 or 16).",
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "source_path")
    FUNCTION = "load_latest"
    CATEGORY = "image"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Always re-run: the newest file can change between prompts.
        return float("NaN")

    def _find_candidates(self, folder_path, filename_prefix):
        """Return matching image paths written since the chain started, newest first."""
        folder_path = folder_path.strip()
        if not folder_path or not os.path.isdir(folder_path):
            logging.warning(f"[LatestImageLoader] Folder not found: '{folder_path}'")
            return []

        # Mirror Save Image: a prefix like "edits/img" means subfolder "edits", names starting with "img".
        prefix = filename_prefix.strip().replace("\\", "/")
        sub_dir, name_prefix = os.path.split(prefix)
        search_dir = os.path.join(folder_path, sub_dir) if sub_dir else folder_path
        if not os.path.isdir(search_dir):
            return []
        name_prefix = os.path.normcase(name_prefix)

        candidates = []
        with os.scandir(search_dir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                name = os.path.normcase(entry.name)
                if not name.endswith(self.SUPPORTED_EXTENSIONS) or not name.startswith(name_prefix):
                    continue
                stat = entry.stat()
                if stat.st_size == 0 or stat.st_mtime < self.chain_start:
                    continue
                candidates.append((stat.st_mtime, entry.path))

        candidates.sort(reverse=True)
        return [path for _, path in candidates]

    @staticmethod
    def _open_image(path):
        """Open and fully load an image so the file handle is released immediately."""
        with Image.open(path) as img:
            img.load()
            return ImageOps.exif_transpose(img) or img.copy()

    def load_latest_from_chain(self):
        """Return (image, path) for the newest readable image in the chain, or (None, None)."""
        # Try newest first; skip files that are unreadable (e.g. still being written).
        for path in self._find_candidates(self.folder_path, self.filename_prefix):
            try:
                return self._open_image(path), path
            except Exception as e:
                logging.warning(f"[LatestImageLoader] Skipping unreadable image '{path}': {e}")
        return None, None

    @staticmethod
    def normalize(img):
        """Convert 16-bit and palette images to modes that can be resized and split into RGB + alpha."""
        if img.mode == "I":
            img = img.point(lambda i: i * (1 / 255))
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        return img

    def downscale(self, img):
        """Shrink to fit max_megapixels, snapped to size_multiple.

        Uses a target size rather than a scale factor, so it's a no-op on an image that already
        fits: the starter is shrunk once and later edits (already at that size) stay unchanged.
        """
        if self.max_megapixels <= 0:
            return img
        w, h = img.size
        target = self.max_megapixels * 1_000_000
        scale = min(1.0, math.sqrt(target / (w * h)))
        m = max(1, self.size_multiple)
        new_w = max(m, int(w * scale) // m * m)
        new_h = max(m, int(h * scale) // m * m)
        if (new_w, new_h) == (w, h):
            return img
        return img.resize((new_w, new_h), Image.LANCZOS)

    @staticmethod
    def save_preview(img):
        """Save a preview to the temp folder with a unique name (avoids browser caching)."""
        preview_name = f"latest_image_preview_{time.time_ns()}.png"
        img.convert("RGB").save(os.path.join(folder_paths.get_temp_directory(), preview_name), compress_level=4)
        return [{"filename": preview_name, "subfolder": "", "type": "temp"}]

    def load_latest(self, image, folder_path, filename_prefix="ComfyUI", mode="continue",
                    max_megapixels=0.0, size_multiple=16, seed=0, unique_id=None):
        self.folder_path = folder_path
        self.filename_prefix = filename_prefix
        self.max_megapixels = max_megapixels
        self.size_multiple = size_multiple
        if unique_id is not None:
            _NODES[str(unique_id)] = self

        starter_path = folder_paths.get_annotated_filepath(image)
        if not os.path.isfile(starter_path):
            raise FileNotFoundError(f"Selected image not found: '{image}'")

        # Start a new chain on first run, when the starter changes, or when asked to.
        if mode == "start from selected" or self.chain_starter != image:
            self.chain_starter = image
            self.chain_start = time.time()
            img, source_path = self._open_image(starter_path), starter_path
        else:
            img, source_path = self.load_latest_from_chain()
            if img is None:
                logging.warning(
                    f"[LatestImageLoader] No new image matching prefix '{filename_prefix}' in '{folder_path}'; "
                    f"using starter image '{image}'. Check that your Save Image prefix matches."
                )
                img, source_path = self._open_image(starter_path), starter_path

        # Same alpha handling as ComfyUI's Load Image (RGBA/LA/transparent palette images).
        img = self.downscale(self.normalize(img))
        rgb = img.convert("RGB")
        if img.mode == "RGBA":
            alpha = np.array(img.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(alpha).unsqueeze(0)
        else:
            mask = torch.zeros((1, rgb.size[1], rgb.size[0]), dtype=torch.float32)

        # Convert to tensor: (1, H, W, 3) float32 [0,1]
        img_tensor = torch.from_numpy(np.array(rgb).astype(np.float32) / 255.0).unsqueeze(0)

        return {
            # The marker key lets the web extension know which nodes to refresh after the run.
            "ui": {"images": self.save_preview(rgb), "latest_image_loader": [True]},
            "result": (img_tensor, mask, source_path),
        }

    @classmethod
    def VALIDATE_INPUTS(cls, image, **kwargs):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True


try:
    from aiohttp import web
    from server import PromptServer

    @PromptServer.instance.routes.post("/latest_image_loader/refresh")
    async def refresh_preview(request):
        """Called by the web extension after a successful run: preview the newest edit in the chain."""
        data = await request.json()
        node = _NODES.get(str(data.get("node_id")))
        if node is None:
            return web.json_response({"images": []})
        img, _ = node.load_latest_from_chain()
        if img is None:
            return web.json_response({"images": []})
        # Preview exactly what the next run will feed into the edit.
        return web.json_response({"images": node.save_preview(node.downscale(node.normalize(img)))})
except Exception as e:  # e.g. running outside ComfyUI
    logging.debug(f"[LatestImageLoader] Refresh route not registered: {e}")
