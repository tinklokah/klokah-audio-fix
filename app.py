import streamlit as st
import requests
import os

# --- 1. 介面設定 ---
st.set_page_config(page_title="族語 API 抓取器", layout="wide")
st.title("🗂️ 族語教材清單抓取與勾選工具")

# 初始化 Session State，這是勾選不失敗的關鍵
if 'tasks' not in st.session_state: st.session_state.tasks = []
if 'sel_dict' not in st.session_state: st.session_state.sel_dict = {}

# --- 2. 狀態更新函數 (按鈕點擊時呼叫) ---
def update_selection(ids, value):
    for tid in ids:
        st.session_state.sel_dict[tid] = value

# --- 3. API 抓取邏輯 ---
user_id = st.text_input("輸入帳號 ID", value="picex11301")

if st.button("🔍 抓取教材清單"):
    try:
        # 抓取 API
        api_url = f"https://web.klokah.tw/text/php/querrySentence.php?id={user_id}"
        res = requests.get(api_url, timeout=15)
        data = res.json()
        
        new_tasks = []
        # 深度掃描 JSON，追蹤 listTitle (大標題)
        def scan_api(obj, current_big_title="未知大單元", current_sub_title=""):
            if isinstance(obj, dict):
                # 取得大標題 (listTitle) 與 小單元名稱
                l_title = obj.get('listTitle') or current_big_title
                s_title = obj.get('title') or obj.get('name') or current_sub_title
                
                for k, v in obj.items():
                    if isinstance(v, str) and (v.endswith('.mp3') or v.endswith('.wav')):
                        # 組合完整的資料夾顯示名稱
                        folder_display = f"【{l_title}】 {s_title}"
                        full_url = v if v.startswith('http') else f"https://web.klokah.tw/text/{v.lstrip('./')}"
                        
                        # 唯一 ID 用於勾選狀態記憶
                        tid = f"{folder_display}_{os.path.basename(v)}"
                        
                        new_tasks.append({
                            "id": tid,
                            "url": full_url,
                            "folder": folder_display,
                            "file": os.path.basename(v)
                        })
                        # 預設勾選
                        if tid not in st.session_state.sel_dict:
                            st.session_state.sel_dict[tid] = True
                    else:
                        scan_api(v, l_title, s_title)
            elif isinstance(obj, list):
                for item in obj:
                    scan_api(item, current_big_title, current_sub_title)

        scan_api(data)
        st.session_state.tasks = new_tasks
        st.success(f"成功抓取！共 {len(new_tasks)} 個音檔。")
    except Exception as e:
        st.error(f"抓取失敗：{e}")

# --- 4. 列表顯示與勾選控制 ---
if st.session_state.tasks:
    # 按照資料夾分組
    grouped = {}
    for t in st.session_state.tasks:
        grouped.setdefault(t['folder'], []).append(t)

    st.write("---")
    
    # 【一鍵全選 / 一鍵取消】 (全域)
    all_ids = [t['id'] for t in st.session_state.tasks]
    c1, c2, _ = st.columns([1, 1, 8])
    c1.button("🌐 全部全選", on_click=update_selection, args=(all_ids, True))
    c2.button("🌐 全部取消", on_click=update_selection, args=(all_ids, False))

    # 顯示分組內容
    for folder in sorted(grouped.keys()):
        items = grouped[folder]
        item_ids = [i['id'] for i in items]
        
        with st.expander(f"📁 {folder} ({len(items)} 個檔案)", expanded=True):
            # 【單元全選 / 取消】
            b1, b2, _ = st.columns([1, 1, 8])
            b1.button(f"全選單元", key=f"all_{folder}", on_click=update_selection, args=(item_ids, True))
            b2.button(f"清空單元", key=f"none_{folder}", on_click=update_selection, args=(item_ids, False))
            
            st.write("")
            # 檔案列表 (三欄顯示)
            cols = st.columns(3)
            for idx, item in enumerate(items):
                with cols[idx % 3]:
                    # 使用 session_state 直接綁定，確保點擊其他按鈕時勾選狀態不消失
                    st.session_state.sel_dict[item['id']] = st.checkbox(
                        item['file'],
                        value=st.session_state.sel_dict.get(item['id'], True),
                        key=f"cb_{item['id']}"
                    )

    # --- 5. 最後確認選取的數量 ---
    selected_count = sum(1 for v in st.session_state.sel_dict.values() if v)
    st.write("---")
    st.info(f"當前已選取： **{selected_count}** / {len(st.session_state.tasks)} 個檔案")
    
    if st.button("🚀 確認並準備下一步"):
        st.write("已確認選單，可以開始進行後續處理。")
