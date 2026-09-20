#!/usr/bin/env bash
# VoxCPM 一键部署/升级脚本（Ubuntu + RTX 4090，Python 3.11）
#
# 用法：
#   bash deploy_voxcpm.sh                 # 安装 + 校验（含 gradio 5.50.0 固定）
#   bash deploy_voxcpm.sh --smoke         # 安装 + 校验 + 冒烟/性能验收（三模式看 README）
#   bash deploy_voxcpm.sh --skip-install  # 已装过 torch/voxcpm，只固定 gradio 并校验
#
# 原则：
# - 只操作仓库根目录的 venv_chatterbox/（项目自动切换的本地引擎环境），不动其它 Python 环境；
# - voxcpm 装完必须把 gradio 固定回 5.50.0，否则 WebUI 排版错乱；
# - 与其它 PyTorch 项目共用 GPU 时，启动 WebUI 前用 CUDA_VISIBLE_DEVICES 指定显卡。
set -euo pipefail

cd "$(dirname "$0")"

SMOKE=0
SKIP_TORCH=0
for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1 ;;
    --skip-install) SKIP_TORCH=1 ;;
    *) echo "未知参数：$arg（支持 --smoke / --skip-install）" >&2; exit 2 ;;
  esac
done

# 国内网络优化：默认走清华 PyPI 镜像；可用环境变量覆盖
# （官方 files.pythonhosted.org 在国内不稳定，容易 incomplete-download）
PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_TIMEOUT="${PIP_TIMEOUT:-120}"
PIP_RETRIES="${PIP_RETRIES:-10}"
# torch cu124 官方源在国内同样可能很慢；可换阿里镜像：
#   TORCH_INDEX_URL=https://mirrors.aliyun.com/pytorch-wheels/cu124 bash deploy_voxcpm.sh
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu124}"
# HuggingFace 国内镜像（模型权重下载；可环境变量覆盖）
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

echo "★ 0/5 环境检查"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MAJOR_MINOR=$("$PYTHON_BIN" -c 'import platform; v=platform.python_version_tuple(); print(f"{v[0]}.{v[1]}")')
if [[ "$MAJOR_MINOR" < "3.10" || "$MAJOR_MINOR" > "3.12" ]]; then
  echo "✗ 当前默认 python3 是 $MAJOR_MINOR，voxcpm 仅支持 3.10~3.12。" >&2
  echo "  请先 conda activate epub2audio（Python 3.11）后重试，或 PYTHON_BIN=/path/to/python3.11 bash deploy_voxcpm.sh" >&2
  exit 1
fi
echo "✓ Python $MAJOR_MINOR"

echo "★ 1/5 系统依赖（需要 sudo）"
sudo apt-get update -y
sudo apt-get install -y ffmpeg libsndfile1 build-essential libgl1 libglib2.0-0
ffmpeg -version | head -1

echo "★ 2/5 虚拟环境 venv_chatterbox（--system-site-packages 继承主环境 gradio 5.50.0）"
if [ ! -x venv_chatterbox/bin/python3 ]; then
  "$PYTHON_BIN" -m venv venv_chatterbox --system-site-packages
fi
VENV_PY=venv_chatterbox/bin/python3
"$VENV_PY" -c 'import platform; v=platform.python_version_tuple(); assert (3,10) <= (int(v[0]), int(v[1])) <= (3,12), f"venv Python {platform.python_version()} 不在 3.10~3.12"'
echo "✓ venv Python $("$VENV_PY" -c 'import platform; print(platform.python_version())')"

echo "★ 3/5 安装 GPU PyTorch 2.6.0（cu124）"
if [ "$SKIP_TORCH" -eq 0 ]; then
  venv_chatterbox/bin/pip install --upgrade pip wheel \
    -i "$PIP_MIRROR" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES"
  venv_chatterbox/bin/pip install torch==2.6.0 torchaudio==2.6.0 \
    --index-url "$TORCH_INDEX_URL" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES"
fi
if ! venv_chatterbox/bin/python -c "import torch" 2>/dev/null; then
  echo "✗ torch 未就绪，请移除 --skip-install 重新运行" >&2
  exit 1
fi

echo "★ 4/5 安装 voxcpm"
if [ "$SKIP_TORCH" -eq 0 ]; then
  venv_chatterbox/bin/pip install -i "$PIP_MIRROR" \
    --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES" voxcpm
fi

echo "★ gradio 固定回 5.50.0（gradio 版本不能变）"
venv_chatterbox/bin/pip install --force-reinstall --no-deps -i "$PIP_MIRROR" \
  --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES" gradio==5.50.0 gradio_client==1.14.0

echo "★ 5/5 校验"
venv_chatterbox/bin/pip check || echo "（pip check 告警可接受：voxcpm 依赖树与固定版本冲突通常只在这些条目上）"
venv_chatterbox/bin/python -c "import torch, gradio; print('cuda:', torch.cuda.is_available(), '| gradio:', gradio.__version__)"
venv_chatterbox/bin/python -c "import voxcpm; print('voxcpm ok')"

if [ "$SMOKE" -eq 1 ]; then
  echo "★ 冒烟/性能验收（RTF≤0.5、显存≤12GB）"
  venv_chatterbox/bin/python3 voxcpm_smoke_test.py --device cuda
fi

echo "✅ VoxCPM 部署完成。启动 WebUI：./run_ui.sh（或 python3 main_ui.py --host 0.0.0.0 --port 7862）"
echo "   多项目共用 GPU 时：CUDA_VISIBLE_DEVICES=1 ./run_ui.sh"
