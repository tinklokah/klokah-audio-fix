import streamlit as st
import requests
import io
import os
import zipfile
import subprocess
import time

# --- 1. 核心後製：FFmpeg 專業濾鏡鏈 ---
def process_audio_ffmpeg(audio_bytes):
    # 使用時間戳記避免暫存檔衝突
    timestamp = int(time.time() * 1000)
    temp_in = f"in_{timestamp}.mp3"
    temp_out = f"out_{timestamp}.mp3"
    
    try:
        with open(temp_in, "wb") as f:
            f.write(audio_bytes)

        # 濾鏡邏輯說明：
        # - silenceremove: 偵測並切除頭尾空白 (前後保留約 0.1-0.2s 緩衝)
        # - afftdn: 專業頻譜降噪 (比 AI 更穩定，不吃資源)
        # - loudnorm: 專業平衡 (I=-18, TP=-6, LRA=7, precision=0.1)
        filter_str = (
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB,"
            "areverse,"
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB,"
            "areverse,"
            "afftdn=nr=12:nt=w,"
            "loudnorm=I=-18:TP=-6:LRA=7:measured_I=-18:measured_TP=-6"
        )

        cmd = [
            "ffmpeg", "-y", "-i", temp_in,
            "-af", filter_str,
            "-ar", "44100", "-b:a", "192k", temp_out
        ]
        
        # 執行 FFmpeg 指令
        subprocess.run(cmd, check=True, capture_output=True)

        with open(temp_out, "rb") as f:
            return f.read()

    except Exception as e:
        st.error(f"後製過程發生錯誤: {e}")
        return audio_bytes # 若失敗則回傳原音檔
    finally:
        # 清理暫存檔
        for t in [temp_in, temp_out]:
            if os.path.exists(t): os.remove(t)

# --- 2. 介面設定與狀態初始化 ---
st.set_page_config(page_title="族語教材專業下載器", layout="wide")
st.title("🎙️ 族語全自動：大單元分類 + 專業音質後製")

if 'tasks' not in st.session_state:
    st.session_state.tasks = []

# --- 3. API 抓取邏輯 (大單元 + 原始 ID 分類) ---
user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 抓取教材層級"):
    try:
        res = requests.get(f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}", timeout=15)
        data = res.json()
        tasks = []
        
        def scan_api(obj, p_folder="未分類"):
            if isinstance(obj, dict):
                parent = obj.get('listTitle') or p_folder
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        parts = v.split('/')
                        original_id = parts[-2] if len(parts) >= 2 else "others"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        filename = os.path.basename(v)
                        
                        tasks.append({
                            "url": full_url, "parent": parent, "child": original_id, "file": filename
                        })
                        # 初始化勾選狀態
                        if f"chk_{full_url}" not in st.session_state:
                            st.session_state[f"chk_{full_url}"] = True
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan_api(i, p_folder)
        
        scan_api(data)
        st.session_state.tasks = tasks
        st.success(f"找到 {len(tasks)} 個音檔。")
    except:
        st.error("API 抓取失敗，請確認 ID 是否正確。")

# --- 4. 顯示與穩定勾選控制 ---
if st.session_state.tasks:
    # 建立顯示樹狀結構
    tree = {}
    for t in st.session_state.tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)

    st.write("---")
    
    # 全域勾選控制 (參考 001.txt 穩定機制)
    ga, gn, _ = st.columns([1, 1, 8])
    if ga.button("🌐 全部全選"):
        for t in st.session_state.tasks: st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if gn.button("🌐 全部取消"):
        for t in st.session_state.tasks: st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    for p_name in sorted(tree.keys()):
        st.header(f"📘 {p_name}")
        child_dict = tree[p_name]
        for c_id in sorted(child_dict.keys()):
            items = child_dict[c_id]
            with st.expander(f"📁 原始路徑 ID: {c_id} ({len(items)} 檔)", expanded=True):
                ca, cn, _ = st.columns([1, 1, 8])
                if ca.button(f"全選 {c_id}", key=f"all_{p_name}_{c_id}"):
                    for i in items: st.session_state[f"chk_{i['url']}"] = True
                    st.rerun()
                if cn.button(f"清空 {c_id}", key=f"none_{p_name}_{c_id}"):
                    for i in items: st.session_state[f"chk_{i['url']}"] = False
                    st.rerun()
                
                cols = st.columns(3)
                for idx, item in enumerate(items):
                    with cols[idx % 3]:
                        # 關鍵綁定邏輯
                        st.session_state[f"chk_{item['url']}"] = st.checkbox(
                            f"🎵 {item['file']}", 
                            key=f"chk_{item['url']}", 
                            value=st.session_state.get(f"chk_{item['url']}", True)
                        )

    # --- 5. 執行下載打包 ---
    final_selection = [t for t in st.session_state.tasks if st.session_state.get(f"chk_{t['url']}", False)]
    st.write("---")
    
    if st.button(f"🚀 2. 開始專業後製並打包 ({len(final_selection)} 個)"):
        if not final_selection:
            st.warning("請先勾選檔案。")
        else:
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w') as master_zip:
                p_bar = st.progress(0)
                st_text = st.empty()
                
                for i, task in enumerate(final_selection):
                    st_text.text(f"雲端後製中: {task['file']}")
                    try:
                        r = requests.get(task['url'], timeout=10)
                        if r.status_code == 200:
                            # 執行 FFmpeg 後製
                            processed = process_audio_ffmpeg(r.content)
                            # 按照層級目錄存入 ZIP
                            master_zip.writestr(f"{task['parent']}/{task['child']}/{task['file']}", processed)
                    except:
                        pass
                    p_bar.progress((i + 1) / len(final_selection))
                
                st_text.text("✨ 處理完成！")
            
            st.download_button(
                label="⬇️ 下載專業平衡包",
                data=zip_io.getvalue(),
                file_name=f"{user_id}_Pro_Audio.zip"
            )
