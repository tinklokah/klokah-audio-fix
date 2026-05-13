import streamlit as st
import requests
import os

# --- 1. 介面與狀態初始化 ---
st.set_page_config(page_title="族語教材穩定勾選版", layout="wide")
st.title("🗂️ 族語教材：大單元 + 原始 ID 分類 (穩定勾選版)")

# 初始化任務列表
if 'tasks' not in st.session_state:
    st.session_state.tasks = []

# --- 2. API 抓取與層級解析 ---
user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 抓取教材層級"):
    try:
        api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
        res = requests.get(api_url, timeout=15)
        data = res.json()
        
        tasks = []
        def scan_api(obj, p_folder="未分類"):
            if isinstance(obj, dict):
                # 抓取大標題 (listTitle)
                parent = obj.get('listTitle') or p_folder
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        # 提取原始路徑中的資料夾 ID (如 70284)
                        parts = v.split('/')
                        original_id = parts[-2] if len(parts) >= 2 else "others"
                        
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        filename = os.path.basename(v)
                        
                        # 參考 001.txt 寫法：使用 URL 作為唯一 Key
                        tasks.append({
                            "url": full_url,
                            "parent": parent,
                            "child": original_id,
                            "file": filename
                        })
                        # 預設勾選狀態 (參考 001.txt)
                        if f"chk_{full_url}" not in st.session_state:
                            st.session_state[f"chk_{full_url}"] = True
                    else:
                        scan_api(v, parent)
            elif isinstance(obj, list):
                for i in obj: scan_api(i, p_folder)

        scan_api(data)
        st.session_state.tasks = tasks
        st.success(f"抓取完成，共 {len(tasks)} 個音檔。")
    except:
        st.error("API 抓取失敗")

# --- 3. 顯示與勾選控制 (完全參考 001.txt 邏輯) ---
if st.session_state.tasks:
    # 建立顯示樹狀結構
    tree = {}
    for t in st.session_state.tasks:
        tree.setdefault(t['parent'], {}).setdefault(t['child'], []).append(t)

    st.write("---")
    
    # 【全域控制按鈕】 (參考 001.txt)
    c_g1, c_g2, _ = st.columns([1, 1, 8])
    if c_g1.button("🌐 全部全選"):
        for t in st.session_state.tasks:
            st.session_state[f"chk_{t['url']}"] = True
        st.rerun()
    if c_g2.button("🌐 全部取消"):
        for t in st.session_state.tasks:
            st.session_state[f"chk_{t['url']}"] = False
        st.rerun()

    # 渲染大單元與子資料夾 (參考 001.txt)
    for p_name in sorted(tree.keys()):
        st.header(f"📘 {p_name}")
        child_dict = tree[p_name]
        
        for c_id in sorted(child_dict.keys()):
            items = child_dict[c_id]
            with st.expander(f"📁 原始路徑 ID: {c_id} ({len(items)} 檔)", expanded=True):
                # 子單元一鍵勾選
                ca, cn, _ = st.columns([1, 1, 8])
                if ca.button(f"全選 {c_id}", key=f"all_{p_name}_{c_id}"):
                    for item in items: st.session_state[f"chk_{item['url']}"] = True
                    st.rerun()
                if cn.button(f"清空 {c_id}", key=f"none_{p_name}_{c_id}"):
                    for item in items: st.session_state[f"chk_{item['url']}"] = False
                    st.rerun()
                
                # 檔案清單
                cols = st.columns(3)
                for idx, item in enumerate(items):
                    with cols[idx % 3]:
                        # 關鍵：key 必須與 session_state 裡的名稱完全一致
                        st.checkbox(
                            f"🎵 {item['file']}", 
                            key=f"chk_{item['url']}", 
                            value=st.session_state[f"chk_{item['url']}"]
                        )
        st.write("---")

    # --- 4. 計算與準備執行 ---
    final_selection = [t for t in st.session_state.tasks if st.session_state.get(f"chk_{t['url']}", False)]
    st.info(f"當前已勾選： **{len(final_selection)}** / {len(st.session_state.tasks)} 個檔案")

    if st.button(f"🚀 確認並打包 (已選 {len(final_selection)} 個)"):
        st.success("勾選狀態已確認，結構正確。")
