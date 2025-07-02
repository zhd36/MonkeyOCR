# PP-DocLayout_plus-L Usage Guide

We have added support for the [PP-DocLayout_plus-L](https://huggingface.co/PaddlePaddle/PP-DocLayout-L) model, which offers improved performance over `doclayout_yolo`.

This guide will walk you through the necessary steps to use the new model.

## How to Use
### **1.  Install Dependencies**

To use `PP-DocLayout_plus-L`, you must install two additional core libraries, **PaddlePaddle** and **PaddleX**, on top of the project's base environment (from `requirements.txt`).

**Step 1: Install PaddlePaddle**

Please choose the command that corresponds to your **NVIDIA driver version** to install the GPU-accelerated version. Make sure your pytorch version is compatible with the PaddlePaddle version you are installing.

```bash
# gpu，requires GPU driver version ≥450.80.02 (Linux) or ≥452.39 (Windows)
 python -m pip install paddlepaddle-gpu==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/

# gpu，requires GPU driver version ≥550.54.14 (Linux) or ≥550.54.14 (Windows)
 python -m pip install paddlepaddle-gpu==3.0.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

**Step 2: Install PaddleX**

Execute the following command to install the base version of PaddleX.
```bash
pip install "paddlex[base]"
```
> ❗ **Note**
> If the installation methods above are not suitable for your environment, or if you wish to explore more options, please refer to the official **[PaddleX](https://github.com/PaddlePaddle/PaddleX)**.
### **2.  Modify the Configuration File**

Update the `model` field in the [`model_configs.yaml`](https://github.com/Yuliang-Liu/MonkeyOCR/blob/main/model_configs.yaml#L7) file at the project root to `PP-DocLayout_plus-L`.

```yaml
layout_config: 
  model: PP-DocLayout_plus-L # PP-DocLayout_plus-L / doclayout_yolo
```
> 💡 Note: The model weights will be downloaded automatically the first time you run the program.  No manual download is required.
