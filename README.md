# ComfyUI Load Latest Image

A ComfyUI custom node for **iterative image editing**, like asking a chat assistant to edit an image, then edit the result, then edit that result again.

The first run loads a starter image you pick. Every run after that loads the **newest image your workflow saved**, so each edit builds on the last one. Queue, tweak the prompt, queue again.

## Features

- **Edit chains.** Starts from your chosen image, then keeps loading the latest saved edit.
- **Easy reset.** Pick a different starter image, or set `mode` to `start from selected`, to begin a new chain.
- **Ignores unrelated images.** Only images that match your Save Image prefix *and* were saved after the chain started are used.
- **Live preview.** When a run finishes, the node's preview updates to the new edit, so you can always see what the next run will start from.
- **Downscale once, not every time.** Optionally shrink large images to a size limit. Edits already within the limit are left alone, so the image doesn't keep getting smaller.
- Handles PNG, JPEG, WebP, BMP and TIFF, EXIF rotation, 16-bit images and transparency (output as a mask).

## Requirements

- A working [ComfyUI](https://github.com/comfyanonymous/ComfyUI) install, recent enough to use the new frontend (2024 or later). Developed and tested on a late-2026 ComfyUI with frontend 1.55.
- No extra Python packages. Everything it uses (`torch`, `numpy`, `Pillow`, `aiohttp`) already comes with ComfyUI.
- Works on Windows, Linux and macOS.

## Installation

### Option 1: git clone (recommended)

Open a terminal in ComfyUI's `custom_nodes` folder and clone the repo:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/stephen82818/comfyui-load-latest-image.git
```

For the Windows portable build, the folder is `ComfyUI_windows_portable\ComfyUI\custom_nodes`.

### Option 2: ComfyUI Manager

In ComfyUI Manager, choose **Install via Git URL** and paste the repository URL.

### Option 3: manual copy

Download the repo as a ZIP and extract it so the files sit directly in their own folder:

```
ComfyUI/custom_nodes/comfyui-load-latest-image/
├── __init__.py
├── latest_image_loader.py
└── web/
    └── latest_image_loader.js
```

### Then

1. **Restart ComfyUI** (the server, not just the browser tab).
2. **Hard-refresh the browser** (Ctrl+F5, or Cmd+Shift+R on Mac) so the preview script loads.
3. Double-click the canvas and search for **Load Latest Image**. It's also under the `image` category.

## Usage

Build a workflow shaped like this:

```
Load Latest Image  ──image──▶  your edit model (Qwen Image Edit, Flux Kontext, Flux 2, …)  ──▶  Save Image
```

1. In **Load Latest Image**, pick or upload your starter image.
2. Set **`filename_prefix`** to exactly the same value as your **Save Image** node's `filename_prefix`. The default for both is `ComfyUI`.
3. Leave **`folder_path`** as ComfyUI's output folder (the default) unless your Save Image writes somewhere else.
4. Write your edit prompt and queue. The first run edits the starter image.
5. Change the prompt and queue again. This run edits the result of the previous one. Repeat as many times as you like.

To **start over**, pick a different starter image or switch `mode` to `start from selected` for one run. To go back to an earlier edit, upload or select that image as the new starter.

### Inputs

| Input | Default | What it does |
|---|---|---|
| `image` | — | Starter image for a new chain (from ComfyUI's `input` folder; you can upload). |
| `folder_path` | ComfyUI `output` folder | Folder your edits are saved to. |
| `filename_prefix` | `ComfyUI` | Must match your Save Image prefix. May include a subfolder, e.g. `edits/img`. Empty matches any image in the folder. |
| `mode` | `continue` | `continue`: load the newest edit. `start from selected`: always load the starter and begin a new chain. |
| `max_megapixels` | `0` (off) | Shrink images larger than this before editing (`1.0` ≈ 1024×1024). Images already within the limit are not touched. |
| `size_multiple` | `16` | When shrinking, round width/height down to a multiple of this (many models need 8 or 16). |
| `seed` | `0` | Not used by the node itself. Set its "control after generate" to `randomize` if you want a visible change every queue. |

### Outputs

| Output | Description |
|---|---|
| `image` | The loaded image. |
| `mask` | Transparency mask (all zeros if the image has no alpha). |
| `source_path` | Full path of the file that was loaded, useful for checking which edit you're on. |

## How it decides what to load

- A **new chain** starts on the node's first run after ComfyUI starts, whenever the starter image changes, or when `mode` is `start from selected`.
- While a chain is going, the node loads the newest image in `folder_path` (plus any subfolder in the prefix) whose name starts with `filename_prefix` **and** that was saved after the chain started. Older files and other workflows' outputs are ignored.
- If no such image exists yet, it uses the starter and prints a warning in the ComfyUI console.

## Troubleshooting

- **It keeps editing the original image.** Your Save Image prefix doesn't match `filename_prefix`, or the files are going to a different folder. Check the console for a `[LatestImageLoader] No new image matching prefix …` warning, and compare `source_path` with where your images are actually saved.
- **The preview doesn't update after a run.** Hard-refresh the browser (Ctrl+F5) and check the browser console (F12) for `[LatestImageLoader]` messages. After a server restart, the preview refresh starts working once the node has run one time.
- **After restarting ComfyUI, it went back to the starter image.** That's expected, because the chain lives in memory. To continue, select your last edit as the new starter.
- **Quality drifts after many edits.** Each pass through the model's VAE loses a little detail and colour accuracy. This comes from the workflow, not the node. Starting a fresh chain from a good result helps.
- **Output folder on a network drive.** The "saved after the chain started" check compares file times with your computer's clock. If the drive's clock is out of sync, new edits may be ignored. Use a local folder.

## License

[MIT](LICENSE)
