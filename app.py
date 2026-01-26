import streamlit as st
import pandas as pd
import json
import os
from github import Github, GithubException

# Page config
st.set_page_config(page_title="CSV Merge & Translate App", layout="wide")

# Constants
DICTIONARY_FILE = "translation_dictionary.csv"

def load_local_dictionary():
    """Load dictionary from local CSV file as DataFrame."""
    if not os.path.exists(DICTIONARY_FILE):
        return pd.DataFrame(columns=["English", "Japanese"])
    try:
        df = pd.read_csv(DICTIONARY_FILE, encoding="utf-8-sig")
        # Ensure columns exist
        if "English" not in df.columns or "Japanese" not in df.columns:
             return pd.DataFrame(columns=["English", "Japanese"])
        
        # Drop fully empty rows, but keep duplicates
        df = df.dropna(subset=["English", "Japanese"], how='all') 
        # Fill NaN with empty string to avoid issues
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"Error loading local dictionary: {e}")
        return pd.DataFrame(columns=["English", "Japanese"])

def save_local_dictionary(df):
    """Save dictionary DataFrame to local CSV file."""
    try:
        df.to_csv(DICTIONARY_FILE, index=False, encoding="utf-8-sig")
        return True
    except Exception as e:
        st.error(f"Error saving local dictionary: {e}")
        return False

# --- GitHub Logic ---
def get_github_repo():
    """Get GitHub repository object."""
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        repo_name = st.secrets.get("REPO_NAME")
        if not token or not repo_name:
            return None
        g = Github(token)
        return g.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub Error: {e}")
        return None

def update_github_dictionary(df):
    """Update dictionary file in GitHub repository."""
    repo = get_github_repo()
    if not repo:
        return False
    
    try:
        # Get content to get sha
        try:
            contents = repo.get_contents(DICTIONARY_FILE)
            sha = contents.sha
            message = "Update dictionary via Streamlit App"
        except GithubException:
            # File doesn't exist, create it
            sha = None
            message = "Create dictionary via Streamlit App"
        
        # Convert DF to CSV string
        content_str = df.to_csv(index=False, encoding="utf-8-sig")
        
        if sha:
            repo.update_file(contents.path, message, content_str, contents.sha)
        else:
            repo.create_file(DICTIONARY_FILE, message, content_str)
            
        return True
    except Exception as e:
        st.error(f"GitHub Update Error: {e}")
        return False

# --- Translation Logic ---
def get_translation_maps(df):
    """
    Create optimized lookup maps from DataFrame.
    Prioritizes the FIRST occurrence in the CSV.
    """
    # EN -> JP: Key is English. Drop duplicates keeping first.
    # We want dict: {En: Jp}
    df_en = df[df["English"] != ""].drop_duplicates(subset=["English"], keep="first")
    en_to_jp = df_en.set_index("English")["Japanese"].to_dict()
    
    # JP -> EN: Key is Japanese. Drop duplicates keeping first.
    # We want dict: {Jp: En}
    df_jp = df[df["Japanese"] != ""].drop_duplicates(subset=["Japanese"], keep="first")
    jp_to_en = df_jp.set_index("Japanese")["English"].to_dict()
    
    return en_to_jp, jp_to_en

def translate_term(text, en_to_jp_map, jp_to_en_map, direction="en_to_jp", missing_terms=None):
    """
    Translate text using pre-computed maps with prefix handling.
    direction: "en_to_jp" or "jp_to_en"
    """
    if pd.isna(text) or text == "":
        return text
    
    import re
    text_str = str(text).strip()
    
    # Prefix regex: Match number at start followed by . or ．
    prefix_match = re.match(r"^(\d+[.．])\s*(.*)", text_str)
    
    if prefix_match:
        prefix = prefix_match.group(1)
        core_term = prefix_match.group(2)
    else:
        prefix = ""
        core_term = text_str
        
    translation = None
    
    # Lookup using maps
    if direction == "en_to_jp":
        translation = en_to_jp_map.get(core_term)
    else:
        # jp_to_en
        translation = jp_to_en_map.get(core_term)
    
    if translation:
        return f"{prefix} {translation}" if prefix else translation
    else:
        # Miss
        if missing_terms is not None:
             missing_terms.add(core_term)
        return text_str

# --- UI Header ---
st.title("CSV結合 & 翻訳ツール")
st.markdown("日本語版リスト(Base)と英語版リスト(Merge)を結合し、辞書ベースで翻訳・補完を行います。")

# --- 1. Dictionary Management ---
st.header("1. 辞書管理")

# Dictionary State (DataFrame)
if "dictionary_df" not in st.session_state:
    st.session_state.dictionary_df = load_local_dictionary()

with st.expander("辞書データを表示 / 編集", expanded=False):
    st.image("https://img.shields.io/badge/GitHub-Integration-blue?logo=github", width=150)
    st.info("※ 上にある行が優先して翻訳に使用されます。（例：同じ英語に対して複数の日本語訳がある場合、上の行が採用されます）")
    
    # Display current dictionary as Table
    st.dataframe(st.session_state.dictionary_df, use_container_width=True)
    
    st.subheader("新規追加")
    col1, col2 = st.columns(2)
    with col1:
        new_key = st.text_input("英語 (Key)", key="dict_key")
    with col2:
        new_val = st.text_input("日本語 (Value)", key="dict_val")
        
    if st.button("辞書に追加して保存"):
        if new_key and new_val:
            # Append new row
            new_row = pd.DataFrame([{"English": new_key, "Japanese": new_val}])
            st.session_state.dictionary_df = pd.concat([st.session_state.dictionary_df, new_row], ignore_index=True)
            
            # Save local
            saved_local = save_local_dictionary(st.session_state.dictionary_df)
            
            # Save to GitHub
            saved_github = False
            if "GITHUB_TOKEN" in st.secrets:
                with st.spinner("GitHubに保存中..."):
                    saved_github = update_github_dictionary(st.session_state.dictionary_df)
            
            # Feedback
            if saved_local:
                if saved_github:
                    st.success(f"ローカルとGitHubの両方に保存しました: {new_key} -> {new_val}")
                elif "GITHUB_TOKEN" in st.secrets:
                    st.warning(f"ローカルには保存しましたが、GitHubへの保存に失敗しました。")
                else:
                    st.success(f"ローカルに保存しました（GitHub未設定）: {new_key} -> {new_val}")
            
        else:
            st.warning("英語と日本語の両方を入力してください。")

# --- 2. File Upload ---
st.header("2. ファイルアップロード")
col_base, col_merge = st.columns(2)

with col_base:
    st.subheader("Base File (日本語)")
    base_file = st.file_uploader("日本語CSVをアップロード", type=["csv"], key="base_uploader")

with col_merge:
    st.subheader("Merge File (英語)")
    merge_file = st.file_uploader("英語CSVをアップロード", type=["csv"], key="merge_uploader")

if base_file and merge_file:
    try:
        # Load CSVs
        def load_csv(uploaded_file):
             try:
                 uploaded_file.seek(0)
                 return pd.read_csv(uploaded_file, encoding='utf-8')
             except UnicodeDecodeError:
                 try:
                     uploaded_file.seek(0)
                     return pd.read_csv(uploaded_file, encoding='cp932')
                 except UnicodeDecodeError:
                     uploaded_file.seek(0)
                     return pd.read_csv(uploaded_file, encoding='shift-jis', encoding_errors='replace')
        
        df_base = load_csv(base_file)
        df_merge = load_csv(merge_file)
        
        st.success("ファイルの読み込みに成功しました。")
        st.write("Base Columns:", list(df_base.columns))
        st.write("Merge Columns:", list(df_merge.columns))
        
        st.divider()
        
        # --- 3. Merge Logic UI ---
        st.header("3. 結合 & 翻訳設定")
        
        st.info("※ 日本語版リスト(Base)の後ろに、英語版リスト(Merge)の行を追加します。")
        
        # A. Column Mapping (For appending Merge rows)
        st.subheader("3-1. 英語版データのマッピング (Column Mapping)")
        st.markdown("""
        英語版(Merge)のデータを日本語版(Base)の列に合わせるための設定です。
        各Base列に対し、対応するMerge列を選択し、必要であれば「翻訳」にチェックを入れてください。
        """)
        
        # Container for mapping
        column_mapping = {}
        
        with st.container():
            # Header row
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.markdown("**Base列 (追加先)**")
            c2.markdown("**Merge列 (データ元)**")
            c3.markdown("**処理**")
            
            # Loop through Base columns
            for base_col in df_base.columns:
                # Default selection logic
                default_idx = 0 # (なし)
                if base_col in df_merge.columns:
                    try:
                        default_idx = list(df_merge.columns).index(base_col) + 1
                    except:
                        pass
                
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.text(f"  {base_col}")
                selected_merge_col = c2.selectbox(
                    f"Select source for {base_col}", 
                    options=["(なし)"] + list(df_merge.columns), 
                    index=default_idx,
                    key=f"map_{base_col}",
                    label_visibility="collapsed"
                )
                
                if selected_merge_col != "(なし)":
                    do_trans_col = c3.checkbox("翻訳", key=f"trans_map_{base_col}", help="チェックするとEN->JP翻訳を実行")
                    column_mapping[base_col] = {"source": selected_merge_col, "translate": do_trans_col}
        
        st.divider()
        
        # B. Add Merge Logic
        st.subheader("3-2. 英語版項目の追加 (Add Columns)")
        st.markdown("Base(日本語版)には無いが、最終リストに残したいMerge(英語版)の列を選択してください。")
        
        cols_to_add = st.multiselect("追加したいMerge側の列", df_merge.columns, key="cols_to_add_multiselect")
        
        # Configuration for each added column
        add_col_configs = {}
        if cols_to_add:
            st.markdown("##### 追加カラムごとの設定")
            for col in cols_to_add:
                with st.expander(f"設定: {col}", expanded=True):
                    c_chk, c_sel = st.columns([1, 2])
                    with c_chk:
                        help_text = f"Base(国内組)の行に対して、この列をどう埋めるか指定します。\nチェックを入れると、指定したBase列の値を英語に翻訳して埋めます。"
                        do_trans = st.checkbox(f"Base行を逆翻訳 (JP->EN)", key=f"trans_{col}", help=help_text)
                    
                    source_col = "(そのままコピー)"
                    with c_sel:
                        if do_trans:
                            source_col = st.selectbox(
                                f"翻訳元Base列", 
                                ["(そのままコピー)"] + list(df_base.columns),
                                key=f"source_{col}",
                                help="翻訳元の日本語データが入っている列を選んでください"
                            )
                        else:
                            st.write(f"※ Base行は空欄になります")
                            
                    add_col_configs[col] = {"do_trans": do_trans, "source_col": source_col}

        # --- 4. Process Button ---
        st.divider()
        if st.button("処理実行"):
            missing_terms = set()
            
            # Prepare Maps (Priority Logic: First match in CSV is used)
            en_map, jp_map = get_translation_maps(st.session_state.dictionary_df)
            
            # Use dataframes
            df_curr_base = df_base.copy()
            df_curr_merge = df_merge.copy()
            
            # --- 1. Prepare Merge Rows (Transformation) ---
            # We want to create a DF from Merge logic that looks like Base
            # Structure: [Base Columns] + [Added Columns]
            
            # Initialize transformed merge df with Base columns
            df_merge_transformed = pd.DataFrame(index=df_curr_merge.index, columns=df_curr_base.columns)
            
            # Apply Mapping (Merge:EN -> Base:JP)
            if column_mapping:
                for base_col, config in column_mapping.items():
                    source_col = config["source"]
                    do_translate_this = config["translate"]
                    
                    # Get source data
                    source_data = df_curr_merge[source_col]
                    
                    if do_translate_this:
                        # Translate term-by-term
                        # Optimization: Get unique values, translate, map back
                        unique_vals = source_data.unique()
                        trans_map = {}
                        for val in unique_vals:
                            trans_map[val] = translate_term(val, en_map, jp_map, "en_to_jp", missing_terms)
                        
                        df_merge_transformed[base_col] = source_data.map(trans_map)
                    else:
                        df_merge_transformed[base_col] = source_data

            # Columns in Base that were NOT mapped remain NaN (correct)
            
            # --- 2. Prepare Added Columns ---
            # Result needs to have [Base Cols] + [Added Cols]
            # Base rows: [Base Cols] (Existing) + [Added Cols] (Reverse Trans or Empty)
            # Merge rows: [Base Cols] (Mapped above) + [Added Cols] (Copy from original Merge)
            
            final_columns = list(df_curr_base.columns) + cols_to_add
            
            # 2a. Expand Base DF with added columns
            for col in cols_to_add:
                config = add_col_configs.get(col, {"do_trans": False, "source_col": "(そのままコピー)"})
                do_reverse = config["do_trans"]
                rev_source = config["source_col"]
                
                new_vals = []
                if do_reverse and rev_source != "(そのままコピー)":
                     # Reverse translate from Base
                     source_data = df_curr_base[rev_source]
                     unique_vals = source_data.unique()
                     trans_map = {}
                     for val in unique_vals:
                         trans_map[val] = translate_term(val, en_map, jp_map, "jp_to_en", missing_terms)
                     new_vals = source_data.map(trans_map)
                else:
                     # Empty
                     new_vals = [None] * len(df_curr_base)
                
                df_curr_base[col] = new_vals

            # 2b. Expand Merge Transformed DF with added columns (Copy from original)
            for col in cols_to_add:
                # Direct copy from original Merge DF
                df_merge_transformed[col] = df_curr_merge[col]
            
            # --- 3. Add Source Indicator (New Feature) ---
            df_curr_base['国内外'] = '日本'
            df_merge_transformed['国内外'] = '海外'

            # --- 4. Concatenate ---
            # Align columns just in case (ensure new column is included)
            # We want '国内外' to be, say, the first column? Or last? 
            # User didn't specify position, but typically last or first is good. 
            # Let's append it to the end by default as it is new.
            
            # Re-align columns to match Base + Added + Indicator
            common_cols = list(df_curr_base.columns)
            # Ensure Merge has all these columns (it should, we built it to match)
            df_merge_transformed = df_merge_transformed.reindex(columns=common_cols)
            
            df_result = pd.concat([df_curr_base, df_merge_transformed], ignore_index=True)

            # Store results in session state
            st.session_state['processing_done'] = True
            st.session_state['result_df'] = df_result
            st.session_state['missing_terms'] = sorted(list(missing_terms)) # Store as list

        # --- Result Display (Persistent) ---
        if st.session_state.get('processing_done'):
            st.success("処理が完了しました！")
            
            # Retrieve from session state
            df_result = st.session_state['result_df']
            missing_terms_list = st.session_state['missing_terms']
            
            # Missing Terms Handling
            if missing_terms_list:
                st.warning(f"辞書未登録の語句が {len(missing_terms_list)} 件あります。")
                
                with st.expander("未登録語句を辞書に追加する (クイック登録)", expanded=True):
                    st.markdown("以下の表に日本語訳を入力し、「辞書に一括追加」ボタンを押してください。")
                    
                    # Prepare Data for Editor
                    # We use a key based on the list content hash or unique ID to prevent reset on simple interactions
                    # But simpler is to reconstruct DF every time, st.data_editor handles state if key is constant-ish.
                    # Warning: if missing_terms_list changes, key should change or DF updates.
                    
                    df_missing_edit = pd.DataFrame({
                        "English": missing_terms_list,
                        "Japanese": [""] * len(missing_terms_list)
                    })
                    
                    edited_df = st.data_editor(
                        df_missing_edit,
                        column_config={
                            "English": st.column_config.TextColumn(disabled=True),
                            "Japanese": st.column_config.TextColumn(required=True)
                        },
                        hide_index=True,
                        key="dict_editor",
                        num_rows="fixed"
                    )
                    
                    if st.button("辞書に一括追加して保存"):
                        to_add = edited_df[edited_df["Japanese"] != ""]
                        if not to_add.empty:
                            # Append to dictionary DF
                            st.session_state.dictionary_df = pd.concat([st.session_state.dictionary_df, to_add], ignore_index=True)
                            
                            # Save
                            save_local_dictionary(st.session_state.dictionary_df)
                            if "GITHUB_TOKEN" in st.secrets:
                                with st.spinner("GitHubに保存中..."):
                                    update_github_dictionary(st.session_state.dictionary_df)
                            
                            st.success(f"{len(to_add)}件を辞書に追加しました！ 再度「処理実行」を押すと反映されます。")
                        else:
                            st.info("追加する訳語が入力されていません。")

            st.dataframe(df_result)
            
            # CSV Download
            csv = df_result.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="CSVをダウンロード (UTF-8 SIG)",
                data=csv,
                file_name='merged_result.csv',
                mime='text/csv',
            )
            
    except Exception as e:
        st.error(f"ファイル処理エラー: {e}")
