import streamlit as st
import requests
import time
import io
import traceback
from PIL import Image

st.set_page_config(page_title="AI 虚拟试衣间", page_icon="👗", layout="wide")

# ========== 阿里云百炼 AI 试衣 API ==========
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com"
CREATE_TASK_URL = f"{DASHSCOPE_BASE}/api/v1/services/aigc/image2image/image-synthesis"
QUERY_TASK_URL = f"{DASHSCOPE_BASE}/api/v1/tasks/{{task_id}}"


def clean_str(s):
    """确保字符串只包含 ASCII 字符，避免 latin-1 编码错误"""
    if s is None:
        return None
    return s.encode("ascii", errors="ignore").decode("ascii")


def upload_to_host(file, host_name):
    """
    上传图片到图床，返回公网 URL。
    支持多个图床，按顺序尝试。
    """
    img = Image.open(file)
    if img.mode in ("RGBA", "P", "CMYK"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    buf.seek(0)
    buf.name = "image.jpg"

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    # ---- uguu.se ----
    if host_name == "uguu.se":
        resp = requests.post(
            "https://uguu.se/upload",
            files={"files[]": (buf.name, buf, "image/jpeg")},
            headers=headers,
            timeout=30,
        )
        resp.encoding = "utf-8"
        data = resp.json()
        if data.get("success") and data.get("files"):
            url = data["files"][0].get("url")
            if url:
                return clean_str(url)

    # ---- SM.MS (需要 API Token) ----
    elif host_name == "sm.ms":
        resp = requests.post(
            "https://sm.ms/api/v2/upload",
            files={"smfile": (buf.name, buf, "image/jpeg")},
            headers=headers,
            timeout=30,
        )
        data = resp.json()
        if data.get("success"):
            url = data.get("data", {}).get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
            # 有时 data 里没有 url 但有 images 字段
            images = data.get("data", {}).get("images")
            if images:
                url = images if isinstance(images, str) else images[0] if isinstance(images, list) else None
                if url and url.startswith("http"):
                    return url

    # ---- ImgBB (需要 API Key) ----
    elif host_name == "imgbb":
        raise Exception("ImgBB 需要 API Key，请使用 uguu.se 或直接粘贴 URL")

    return None


def submit_try_on(api_key, person_url, top_url, bottom_url, model="aitryon", resolution=-1, restore_face=True):
    """提交 AI 试衣任务到阿里云百炼"""
    # 清理所有输入，确保纯 ASCII
    api_key = clean_str(api_key)
    person_url = clean_str(person_url)
    top_url = clean_str(top_url) if top_url else None
    bottom_url = clean_str(bottom_url) if bottom_url else None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }

    payload = {
        "model": model,
        "input": {"person_image_url": person_url},
        "parameters": {"resolution": resolution, "restore_face": restore_face},
    }
    if top_url:
        payload["input"]["top_garment_url"] = top_url
    if bottom_url:
        payload["input"]["bottom_garment_url"] = bottom_url

    resp = requests.post(CREATE_TASK_URL, headers=headers, json=payload)
    data = resp.json()

    if resp.status_code != 200 or "output" not in data:
        error_msg = data.get("message", str(data))
        raise Exception(f"创建任务失败: {error_msg}")

    return data["output"]["task_id"]


def wait_for_result(api_key, task_id):
    """轮询任务结果，返回 (image_url, status_log)"""
    api_key = clean_str(api_key)
    headers = {"Authorization": f"Bearer {api_key}"}
    max_wait = 180
    started = time.time()
    log = []

    while time.time() - started < max_wait:
        resp = requests.get(QUERY_TASK_URL.format(task_id=task_id), headers=headers)
        data = resp.json()
        output = data.get("output", {})
        status = output.get("task_status", "UNKNOWN")

        log.append(status)

        if status == "SUCCEEDED":
            return output.get("image_url"), log
        elif status == "FAILED":
            msg = output.get("message", "未知错误")
            raise Exception(f"任务失败: {msg}")
        elif status == "CANCELED":
            raise Exception("任务已取消")

        time.sleep(3)

    raise Exception("任务超时（超过 3 分钟）")


# ========== UI ==========
st.title("👗 AI 虚拟试衣间")
st.markdown("阿里云百炼 AI 试衣 API · OutfitAnyone 模型 · [免费注册](https://bailian.console.aliyun.com)")

# ----- 侧边栏 -----
with st.sidebar:
    st.header("⚙️ 设置")

    api_key = st.text_input(
        "阿里云百炼 API Key",
        type="password",
        placeholder="sk-xxxxxxxxxxxxxxxx",
        help="[bailian.console.aliyun.com](https://bailian.console.aliyun.com) → API-KEY 管理",
    )

    st.divider()

    model_choice = st.selectbox(
        "模型",
        options=["aitryon", "aitryon-plus"],
        format_func=lambda x: (
            "AI试衣-基础版 (0.20元/张, ~15s)"
            if x == "aitryon"
            else "AI试衣-Plus版 (0.50元/张, ~30s, 效果更好)"
        ),
    )

    st.divider()

    st.subheader("📤 图片上传方式")
    st.markdown("""
    **推荐：直接粘贴 URL**（最稳定）

    如需上传本地图片，可选择 uguu.se 图床自动上传。
    或者将图片上传到[阿里云 OSS](https://oss.console.aliyun.com) 后粘贴 URL。
    """)

    st.caption(f"💰 每次 {model_choice == 'aitryon' and '0.20' or '0.50'} 元 · 🎁 新用户免费 400 张")

# ----- 主区域 -----
st.markdown("### ① 上传图片或填写 URL")
st.caption("图片自动上传到 uguu.se 图床（如未勾选则需手动粘贴公网 URL）")

col1, col2 = st.columns(2)

with col1:
    st.subheader("📷 人物照片")
    person_file = st.file_uploader("上传人物照片", type=["jpg", "jpeg", "png", "webp", "bmp", "heic"], key="person")
    if person_file:
        st.image(person_file, use_container_width=True)
    person_url = st.text_input("或直接粘贴人物照片的公网 URL", placeholder="https://example.com/person.jpg", key="person_url_direct")

with col2:
    st.subheader("👔 衣服图片")
    tab1, tab2 = st.tabs(["上装/连衣裙", "下装（可选）"])
    with tab1:
        top_file = st.file_uploader("上装或连衣裙", type=["jpg", "jpeg", "png", "webp", "bmp", "heic"], key="top")
        if top_file:
            st.image(top_file, use_container_width=True)
        top_url = st.text_input("或粘贴上装 URL", placeholder="https://...", key="top_url_direct")
    with tab2:
        bottom_file = st.file_uploader("下装（裤子/裙子）", type=["jpg", "jpeg", "png", "webp", "bmp", "heic"], key="bottom")
        if bottom_file:
            st.image(bottom_file, use_container_width=True)
        bottom_url = st.text_input("或粘贴下装 URL", placeholder="https://...", key="bottom_url_direct")

use_upload = st.checkbox("📤 自动上传到图床（uguu.se，免费无需注册）", value=True)

with st.expander("⚙️ 高级参数"):
    col_a, col_b = st.columns(2)
    with col_a:
        resolution = st.selectbox(
            "输出分辨率",
            options=[-1, 1024, 1280],
            format_func=lambda x: {-1: "保持原图", 1024: "1024 (576×1024)", 1280: "1280 (720×1280)"}[x],
        )
    with col_b:
        restore_face = st.checkbox("保留原人脸", value=True)

# ----- 提交 -----
if st.button("✨ 开始试穿", type="primary", use_container_width=True):
    if not api_key:
        st.error("请在左侧输入阿里云百炼 API Key")

    person_final = person_url.strip() if person_url else None
    top_final = top_url.strip() if top_url else None
    bottom_final = bottom_url.strip() if bottom_url else None

    # 自动上传
    upload_errors = []

    def resolve_upload(file_obj, direct_url, label):
        """如果没填 URL 但上传了文件，就自动传到图床"""
        if direct_url and direct_url.strip():
            return direct_url.strip(), None
        if file_obj and use_upload:
            with st.spinner(f"正在上传{label}到 uguu.se..."):
                url = upload_to_host(file_obj, "uguu.se")
                if url:
                    st.success(f"{label}上传成功")
                    return url, None
                else:
                    return None, f"{label}上传失败，请换用 URL 粘贴方式"
        elif file_obj and not use_upload:
            return None, "已上传图片但未勾选自动上传，请粘贴 URL 或勾选自动上传"
        return None, None

    person_final, err = resolve_upload(person_file, person_url, "人物照片")
    if err:
        upload_errors.append(err)
    top_final, err = resolve_upload(top_file, top_url, "上装")
    if err:
        upload_errors.append(err)
    bottom_final, err = resolve_upload(bottom_file, bottom_url, "下装")
    if err:
        upload_errors.append(err)

    if upload_errors:
        for e in upload_errors:
            st.error(e)
        st.stop()

    if not person_final:
        st.error("请上传人物照片或填写 URL")
        st.stop()
    if not top_final and not bottom_final:
        st.error("请至少提供一件衣服（上装或下装）")
        st.stop()

    # 显示使用的 URL
    with st.expander("🔗 图片链接（点击展开）"):
        st.caption(f"人物: {person_final}")
        if top_final:
            st.caption(f"上装: {top_final}")
        if bottom_final:
            st.caption(f"下装: {bottom_final}")

    # 提交 + 轮询
    try:
        with st.spinner("正在提交试衣任务..."):
            task_id = submit_try_on(api_key, person_final, top_final, bottom_final, model_choice, resolution, restore_face)
        st.success(f"任务已创建: `{task_id}`")

        status_placeholder = st.empty()
        progress_bar = st.progress(0)

        def poll_with_ui():
            safe_key = clean_str(api_key)
            headers = {"Authorization": f"Bearer {safe_key}"}
            max_wait = 180
            started = time.time()
            last_status = ""

            while time.time() - started < max_wait:
                resp = requests.get(QUERY_TASK_URL.format(task_id=task_id), headers=headers)
                data = resp.json()
                output = data.get("output", {})
                status = output.get("task_status", "UNKNOWN")

                if status != last_status:
                    status_placeholder.info(f"任务状态: {status}")
                    last_status = status

                progress_map = {
                    "PENDING": 10, "PRE-PROCESSING": 20, "RUNNING": 50,
                    "POST-PROCESSING": 80, "SUCCEEDED": 100,
                }
                progress_bar.progress(progress_map.get(status, 30))

                if status == "SUCCEEDED":
                    return output.get("image_url")
                elif status == "FAILED":
                    msg = output.get("message", "未知错误")
                    raise Exception(f"任务失败: {msg}")
                elif status == "CANCELED":
                    raise Exception("任务已取消")

                time.sleep(3)

            raise Exception("任务超时（超过 3 分钟）")

        result_url = poll_with_ui()
        progress_bar.empty()
        status_placeholder.empty()

        st.success("✅ 试穿完成！")
        st.image(result_url, caption="试穿效果图", use_container_width=True)
        st.caption(f"图片 24 小时内有效：[点击查看原图]({result_url})")

    except Exception as e:
        st.error(f"出错了: {e}")
        with st.expander("🔍 错误详情"):
            st.code(traceback.format_exc())

# ----- 底部 -----
st.markdown("---")
st.markdown("""
**使用说明**:
1. 在 [阿里云百炼控制台](https://bailian.console.aliyun.com) 免费注册，创建 API Key
2. 上传图片或直接粘贴公网 URL（推荐用 [阿里云 OSS](https://oss.console.aliyun.com) 托管图片）
3. 勾选「自动上传到图床」可将本地图片上传到 uguu.se
4. 处理约 15-30 秒，新用户免费 400 张

**图片要求**: 人物正面全身、背景简洁 · 衣服平铺、光照均匀、占画面主体
""")
