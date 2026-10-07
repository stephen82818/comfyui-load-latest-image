"""Iterative image editing over the Comfy SDK.

The API version of the Load Latest Image node: start from an image, then each prompt edits
the result of the previous one. The chain is kept here, in the client, so it works against
any Comfy API v2 target (a local ComfyUI behind comfy-api-proxy, a Comfy API deployment, or
Comfy Cloud), where each job runs on its own and nothing is kept between jobs.

    python edit_chain.py photo.png "make it night" "add snow" "turn it into a watercolor"
    python edit_chain.py photo.png            # no prompts: type them one at a time

The target comes from COMFY_BASE_URL (and COMFY_API_KEY for hosted targets).
"""

import argparse
import mimetypes
import random
import sys
from pathlib import Path

from comfy_sdk import Comfy

DEFAULT_WORKFLOW = Path(__file__).resolve().parent.parent / "workflows" / "edit_chain_api.json"


def find_node(graph, class_type):
    """Return the id of the only node of this class in the graph."""
    ids = [node_id for node_id, node in graph.items() if node.get("class_type") == class_type]
    if len(ids) != 1:
        sys.exit(f"Expected exactly one {class_type} node in the workflow, found {len(ids)}.")
    return ids[0]


class EditChain:
    def __init__(self, client, workflow_path, out_dir, seed=None):
        self.client = client
        self.workflow_path = workflow_path
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(seed)
        self.current = None  # asset handle for the image the next edit starts from
        self.step = 0

        graph = client.workflows.from_file(workflow_path).json
        self.loader_id = find_node(graph, "LatestImageLoader")
        self.prompt_id = find_node(graph, "CLIPTextEncode")
        self.noise_id = find_node(graph, "RandomNoise")
        self.save_id = find_node(graph, "SaveImage")

    def start(self, image_path):
        self.current = self.client.assets.from_file(image_path)
        self.step = 0

    def edit(self, prompt):
        """Run one edit on the current image and make the result the new current image."""
        wf = self.client.workflows.from_file(self.workflow_path)
        wf.set_input(self.loader_id, "image", self.current)
        # Each job stands alone, so the loader always uses the image it is given.
        wf.set_input(self.loader_id, "mode", "start from selected")
        wf.set_input(self.prompt_id, "text", prompt)
        wf.set_input(self.noise_id, "noise_seed", self.rng.randrange(2**50))

        job = self.client.run(wf)
        outputs = job.get_outputs(self.save_id)
        if not outputs:
            raise RuntimeError(f"Job {job.id} finished without saving an image.")

        data = outputs[0].to_bytes()
        self.step += 1
        ext = mimetypes.guess_extension(outputs[0].content_type) or ".png"
        path = self.out_dir / f"step_{self.step:02d}{ext}"
        path.write_bytes(data)

        # Uploads are content-addressed, so feeding the result back in is a cheap re-upload.
        self.current = self.client.assets.from_bytes(data, filename=path.name)
        return path


def main():
    parser = argparse.ArgumentParser(description="Chain image edits through the Comfy SDK.")
    parser.add_argument("image", help="starter image")
    parser.add_argument("prompts", nargs="*", help="edit prompts, applied in order (omit to type them one at a time)")
    parser.add_argument("--workflow", default=str(DEFAULT_WORKFLOW), help="API-format edit workflow")
    parser.add_argument("--out", default="edits", help="folder for the results (default: edits)")
    parser.add_argument("--seed", type=int, help="seed for reproducible chains")
    args = parser.parse_args()

    chain = EditChain(Comfy(), args.workflow, args.out, args.seed)
    chain.start(args.image)

    if args.prompts:
        for prompt in args.prompts:
            print(f"[{chain.step + 1}] {prompt}")
            print(f"    -> {chain.edit(prompt)}")
        return

    print("Type an edit and press Enter. 'restart' goes back to the starter image, an empty line quits.")
    while True:
        try:
            prompt = input(f"edit {chain.step + 1}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            break
        if prompt == "restart":
            chain.start(args.image)
            print("Back to the starter image.")
            continue
        print(f"    -> {chain.edit(prompt)}")


if __name__ == "__main__":
    main()
