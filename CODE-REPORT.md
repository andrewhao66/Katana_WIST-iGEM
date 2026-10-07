# Katana / Kagami 程式碼解析報告

> 審閱範圍：`main` @ `8a8dfe4`，94 個受控檔案、約 9,000 行 Python（不含 18,539 行參考資料 TSV）。
> 本報告的每一項行為描述都來自讀原始碼，並且在本機實際執行驗證過（執行結果見第 10 節）。
> 撰寫日期 2026-10-07。

---

## 1. 一句話定位

這不是一套合成生物學設計工具，而是一套**「名稱與序列不得脫鉤」的強制執行機制**。

它不幫你設計任何東西：不產生序列、不最佳化密碼子、不替你選部件。它做的是一件更窄、也更難的事——
確保你**以為**手上拿的那段 DNA，就是你**實際**拿的那段 DNA。整個 repo 可以看成同一個命題的兩個方向：

| 方向 | 工具 | 問的問題 |
|---|---|---|
| 正向 | **Katana** (`katana_build.py` 等) | 「照這份設計意圖，從封存的部件組出來的序列是什麼？」 |
| 反向 | **Kagami**（`kagami/`，日文「鏡」） | 「手上這段別人給的序列，裡面到底是什麼部件？標籤說的是真的嗎？」 |

正向產生可重現的建構；反向審核任何來源的序列。兩者共用同一套雜湊慣例與同一組判定語彙，
所以一邊的 PASS 和另一邊的 PASS 意思相同。

---

## 2. 它要解決的問題：五次真實失效

`README.md` 開頭列出五次實際發生的事故，這五件事是整個架構的設計依據——每一條規則都對應一次已經犯過的錯：

| # | 發生什麼 | 本質 | 架構上的對策 |
|---|---|---|---|
| 1 | 兩個建構中標為 `B0032` 的部件，裝的是 `B0034` 的序列（轉譯速率差 3 倍） | 標籤 ≠ 內容 | **Spec 格式裡沒有任何可以寫序列的欄位** |
| 2 | ORF finder 的最小長度門檻，從 16.5 kb operon 中無聲丟掉一個 72-aa 的 GvpA；該建構已標記為 sealed | 自我一致的錯誤答案 | 座標只能取自**已註解**的記錄，不得用 ORF 掃描 |
| 3 | 0-based Python 切片被當成 1-based 座標寫下，已流到對外的廠商文件 | 差一錯誤 | 座標與其慣例一起記錄；`find_part.py` 專門處理這個轉換 |
| 4 | 同一建構存在三份副本，兩份過期，其中一份檔名與 sealed 版完全相同 | 無單一真相來源 | 建構是**生成物**，不是來源；永不手改 |
| 5 | 檔名寫 `…__47c4687cca62.gb` 的部件檔，其序列雜湊為 `3c840d2b…`（同長度、不同鹼基） | 檔名與內容脫鉤 | 檔名內嵌序列雜湊 + 使用時重算比對 |

第 2 條最值得注意，因為**第一次抓它的檢查是通過的**：建置腳本把抽出的 operon 拿去跟「抽取來源的那個檔案」
比對——它在改自己的考卷。只有指向獨立的、已註解的來源時，檢查才真的生效。這個洞見直接長成了
`kg_bridge.py` 裡的「循環來源禁令」。

---

## 3. 核心理念（讀程式時真正該抓住的三句話）

### 3.1 「Design Spec + 封存部件庫 = 真相；建構檔 = 生成物」

`ARCHITECTURE.md` 的第一句話，而且幾乎推導出其他所有東西。如果建構是生成的，它就能被重新生成；
能重新生成，兩次結果就能比對。於是「這個檔案對不對？」（人無法回答）變成
「這個檔案是否等於 Spec + 部件庫生出來的東西？」（電腦可以回答）。

實務後果是一條聽起來嚴苛、實際上很解放的規則：**你永遠不編輯建構**。要改就改 Spec 然後重建。

### 3.2 「ID 是唯一的指稱方式」——把錯誤從「不太可能」變成「無法表達」

這是整個專案最高價值的設計決策，而且它是**由缺席實現的**。
看 `specs/pSense-Nit.spec.yaml`：有 `id`、`role`、`class`、`source`、`seal`、`architecture.order`、`trims`——
就是**沒有任何欄位可以放鹼基**。

```yaml
parts:
  - id: sfGFP
    role: reporter
    class: reference
    source: { registry: iGEM, part: BBa_I746916 }
    seal:   { status: SEALED, lib: "sfGFP__v1__08a1e654bd76.gb",
              seq_sha256_12: 08a1e654bd76, length: 720 }
architecture:
  order: [PyeaR, RBS_sfGFP_med, sfGFP, B0015]
```

你**無法**在 Spec 裡貼錯序列，因為沒有地方可以貼。`katana_init.py` 的模板註解把這點講得很直白，
`AGENTS.md` 規則 2 則把它變成對 AI 助理的指令：「如果你想加一個 sequence 欄位，你找到的是失效模式，不是缺少的功能。」

### 3.3 「讀取時不信任任何東西」

驗證不是部件入庫時做一次的動作，而是**每次使用時都發生**。Stage 1 已經比對過 Spec 的 pin 與 manifest，
Stage 2 還是要重讀檔案、重算雜湊。這不是冗餘：

- Stage 1 比對的是「Spec 裡的聲明」對「manifest 裡的聲明」——兩份 metadata 互相同意。
- Stage 2 比對的是「磁碟上的實際位元組」對「manifest」。

被編輯器重存、被同步工具截斷、被任何東西改過的檔案，會通過 Stage 1 而在 Stage 2 失敗。

### 3.4 `class` 這個分岔是承重結構

| class | 意思 | 攜帶什麼 | SBOL 來源邊 |
|---|---|---|---|
| `reference` | 從一級來源取得 | `source:`（accession + 座標，或 Registry 部件） | `wasDerivedFrom` |
| `designed` | 由工具算出（密碼子最佳化、RBS 調校） | `design_record:`（工具、host、版本） | `wasGeneratedBy` |
| `synthesised` | 照寫的樣子訂購 | design record | `wasGeneratedBy` |

一個 designed 部件沒有 accession 可以指。把它記成「derived from」某個 accession 是假的，所以引擎不這麼做。
這個區分一路影響到 Stage-4b 的 CAI 檢查（只檢查 `class=designed` 的 CDS）和 SBOL 的 PROV-O 邊。

---

## 4. 檔案地圖

### 4.1 正向引擎（repo 根目錄）

| 檔案 | 行數 | 職責 |
|---|---|---|
| `katana_build.py` | 901 | **建置引擎**。Stage 1–6 全在這裡。唯一的真正入口 |
| `katana_lock.py` | 91 | 完整性核心：`row_sha256` / `lock_root` / `resolve()`。無第三方依賴 |
| `verify_library_v2.py` | 72 | 部件庫稽核：逐列檢查檔案存在、file hash、seq hash、檔名 sha12、row manifest、孤兒檔、root |
| `test_seal_gaps.py` | 67 | **對抗性測試**：在拋棄式副本上實際執行破壞，斷言每種都被抓到 |
| `verify.py` | 103 | 上面兩者的零依賴包裝（`python3 verify.py` 即可） |
| `test_determinism.py` | 290 | 核心主張的可執行證明：oracle / 可重複 / pin / 竄改 / SBOL 五路 |
| `add_part.py` | 540 | **入庫閘門**。NCBI / iGEM Registry / 本地檔 / 他庫複製四種來源 |
| `find_part.py` | 392 | 把「我要大腸桿菌的乳酸感應抑制子」變成 accession + 座標 |
| `get_genome.py` | 384 | 按需取得宿主基因組（23 種生物選單，依 iGEM White List） |
| `check_design.py` | 323 | **生物學健全性檢查**（與雜湊完全無關的另一半） |
| `katana_drylab.py` | 155 | Stage-4b 乾實驗閘：off-target + 密碼子品質 |
| `blast_offtarget.py` | 57 | 純 Python seed-and-extend 同源掃描 |
| `katana_sbol.py` | 283 | SBOL 3 匯出（選用） |
| `katana_order_table.py` | 74 | 廠商訂購用 CSV |
| `katana_init.py` | 184 | 建立**你自己的**部件庫（本 repo 的庫保持封存） |

### 4.2 反向稽核器（`kagami/`）

| 檔案 | 行數 | 職責 |
|---|---|---|
| `kagami.py` | 558 | CLI + 協調 + 文字/JSON/HTML 報告 + `--registry` 聲明查核 |
| `kg_parse.py` | 259 | FASTA / GenBank / **csv / tsv / xlsx / 裸貼上** 讀取器 |
| `kg_identify.py` | 405 | blastn 分解 → blocks；無 blastn 時退化為註解特徵精確比對 |
| `kg_audit.py` | 502 | **所有檢查都在這裡**。五級判定（FAIL/FLAG/NOTE/SKIP/PASS） |
| `kg_refs.py` | 231 | 參考部件集載入 + `--library` 雜湊閘 + 信任分層 |
| `kg_registry.py` | 136 | iGEM Registry 即時用戶端（含 429 退避） |
| `kg_bridge.py` | 133 | 回到正向 Katana 的橋：intake 請求 + 草稿 Spec |
| `kg_rebuild.py` | 217 | 一鍵「稽核 → 從一級來源封存 → 重建乾淨建構」 |
| `kg_verdict.py` | 31 | 引擎執行結果的措辭（兩個前端共用，避免漂移） |
| `kagami_gui.py` | 551 | tkinter 視窗（零依賴，學校電腦可跑） |
| `kg_katana_tabs.py` | 411 | 把正向引擎包進 GUI 的 Build / Library 頁籤 |
| `build_refs.py` | 458 | 重建參考集（含 fail-closed 雜湊閘與 IP 邊界） |
| `tests.py` | 630 | 88 項自足檢查 |

---

## 5. 資料模型

### 5.1 部件庫：三層雜湊，各抓不同的東西

目錄是 `parts-library/ref_parts/`，一個部件一個檔，命名 `<id>__v<n>__<序列雜湊前12碼>.gb`，
加上 `LOCK.tsv`（manifest）與 `LOCK.root`（根雜湊）。

```
id  version  seq_sha256  file_sha256  length  source  date  class  outfile  row_sha256
```

| 雜湊 | 定義 | 抓什麼 |
|---|---|---|
| `seq_sha256` | `sha256(UPPER(只取字母))` | **鹼基變了** |
| `file_sha256` | `sha256(原始位元組)` | 鹼基沒變但**檔案變了**（註解、空白、行尾） |
| `row_sha256` | `sha256("k=v\n"...)` 跨 9 個承重欄位 | **manifest 本身被編輯**（accession、版本、class、outfile 被偷改） |
| `LOCK.root` | `sha256(所有 row_sha256 以 \n 串接)` | 有列被**新增 / 刪除 / 修改** |

`row_sha256` 的欄位順序是固定的，而且在**四個檔案裡重複定義**
（`katana_lock.FIELDS`、`add_part.FIELDS`、`katana_init.FIELDS`、`build_refs.LOCK_FIELDS`），
每處都有註解說明這個重複是**故意的且承重**——一旦漂移，該工具產出的列就沒人能重算。

部件是**不可變的**。沒有原地編輯：修正過的部件是新版本、新雜湊，舊列留著。`add_part.py` 明確拒絕：

```
BLOCK: lldR v1 is already in this library. Parts are never edited in place
       - admit a new version instead
```

### 5.2 完整性模型與它老實承認的那個極限

`verify_lock_root()` 做兩個獨立檢查：

1. **自洽性——永遠開著。** 從 row 雜湊重算 root，必須等於 `LOCK.root` 檔案。
2. **外部 pin——只有你給 `--expect-root` 時。** root 還必須等於你從別處帶來的雜湊。

第二項存在，是因為第一項有個真實極限：**一個部件庫可以內部完全自洽，同時卻是錯的部件庫。**
過期的同步、舊的 checkout、第二台機器——每一個都給你一份描述著你並不想對照的部件的、完美自洽的 manifest。
只有庫外帶進來的 pin 能抓這個。

所以引擎拒絕裝作沒事：沒有 pin 時，它**每次執行都明說**，而不是印一個令人安心的勾。

### 5.3 一個真實的「同名不同物 / 不同名同物」案例

`LOCK.tsv` 裡 `RBS_hrpS` v2 與 `RBS_lldR_strong` v2 的 `seq_sha256` 完全相同
（`d0e539d22e8f91fc…`）。這就是 `find_part.py:99-115` 與 `pAP-Logic` v8 變更說明裡記錄的事故：
兩個不同名字的 RBS 做出來是位元組相同的，在同一建構裡用上兩個就形成 43 bp 的精確正向重複
——超過 ~40 bp 的 recA 重組基質門檻，也是多數合成廠商會標記的東西。

`find_part.py --have` 現在會主動報告這件事：

```
NOTE: different names, identical sequence -
      RBS_hrpS = RBS_lldR_strong
      Using two of these in one construct creates an exact direct repeat.
```

註解寫得很誠實：「資訊一直都在 manifest 裡；只是從來沒有東西去看。」

---

## 6. 正向管線：Stage 1–6 逐段

```
Design Spec ─┐
             ├─> 1 SOURCE   → 2 VERIFY → 3 ASSEMBLE → 4 VALIDATE → 4b DRY-LAB → 5 SEAL → 6 DIFF
部件庫 ──────┘                                                                      │
                                                            .gb + .fasta + .ttl + .csv + seq_sha256
```

**每一關都是 BLOCK，不是 warning。** 這是刻意的，也是最可能惹你的性質，同時是引擎值得擁有的理由：
長 log 裡的 warning 是沒人看的 warning。

### Stage 1 — SOURCE（`resolve_parts`，`katana_build.py:209`）

- 沒有 `seal` 區塊的裸 id 直接拒絕。
- 在 LOCK 中按 id 尋找，**取版本號最大的那一列**。
- 比對 Spec 的 `seq_sha256_12` pin 與 LOCK 的 `seq_sha256`，不符即 BLOCK。
- 載入 `.gb` 檔（找不到就退回 LOCK 的 `outfile` 欄位）。

每個 BLOCK 訊息都附上「下一步該打什麼指令」，這在整個 repo 裡很一致：

```
BLOCK Stage-1: part 'lldR' is not in your Parts Library yet.
       See what you have:      python3 find_part.py --have
       Find it on NCBI:        python3 find_part.py lldR
       Copy one we ship:       python3 add_part.py --library <yours> --from ... --id lldR
```

### Stage 2 — VERIFY（同函式內）

重算 `seq_sha256(raw_seq)` 與 LOCK 比對，並檢查長度等於 Spec 宣告的 `seal.length`。
`seq_sha256` 的正規化只有一步：`seq.upper()` 然後 ASCII 編碼。註解坦白說明
KATANA_SPEC v2 §3.4 本來規定要加 `|topology` 標籤，但現存的 LOCK 與所有已封存部件用的是純 UPPER，
所以引擎遵循既成慣例以重現 oracle——這是「說出來的技術債」而非偷偷的偏離。

### Stage 3 — ASSEMBLE（`assemble_insert`，`:327`）

依 `architecture.order` 串接，套用 `trims`。trim 是**宣告式的**：

```yaml
trims:
  PyeaR:
    3prime: AGGAGGGAAAAGGATG   # 16 nt 原生 SD+ATG
```

你寫的是**要被移除的實際鹼基**，不是座標。`apply_trims` 驗證該序列真的在端點上，否則 BLOCK。
這直接消滅了差一錯誤（失效 #3）：沒有數字可以寫錯。

同時產生 GenBank feature 清單（1-based 座標）、記錄 `consumed_inputs`（每個部件的雜湊）。
`role` 透過 `feature_key_map` 映射到 GenBank feature key。

### Stage 4 — VALIDATE（`validate_insert`，`:455`）

刻意**先做正面不變量**（而不是只檢查「沒有壞東西」）：

1. insert 非空
2. 長度 == Σ(修剪後的部件長度)
3. 每個部件修剪後的子序列都能在 insert 中**定位**

然後才是接合處檢查（RBS→ATG 的 ATG 存在）、禁用限制酶位點（**只有跨越接合處的才 BLOCK**，
部件內部的位點對 de novo 合成無關緊要，只作資訊）、GC 含量 25–65%、同聚物 ≤10 bp、片段大小上限。

### Stage 4b — DRY-LAB（`katana_drylab.py`）

**Off-target**：拿 insert 去掃宿主全基因組，找「沒有任何預期部件能解釋的」長段高相似。

- **預期**＝落在某個宿主來源部件基因組位點 ±2 kb 內的命中 → INFO
- **BLOCK**＝≥100 bp 且 ≥95% 相似、**不在**任何預期位點 → 錯裝 / 錯部件 / 重編碼漂回原生基因
- **WARN**＝40–100 bp 的非預期命中 → 給人看一眼，不阻擋

門檻的理由寫在程式裡：「那麼長又那麼精確的匹配從不是巧合。」

**密碼子品質**：對每個 `class=designed` 的 CDS 算真實的大腸桿菌 CAI（幾何平均），
< 0.75 BLOCK，< 0.80 WARN。

**關鍵設計**：缺依賴或缺基因組 → **大聲 WARN，絕不無聲跳過**。
`katana_build.py:785-788` 把整個 Stage-4b 用 try/except 包起來，連模組 import 失敗都會印
「NOT enforced this run」。`ARCHITECTURE.md` 說明理由：「無聲消失的選用檢查比沒有檢查更糟，
因為它讓你以為自己被保護著。」

### Stage 5 — SEAL（`:796`）

寫 `.gb` 與 `.fasta`，然後**重讀寫出的 .gb、重算雜湊、與記憶體中的值比對**。
`add_part.py` 做同樣的事（寫入後重讀，不符就刪檔並拒絕記錄），註解一句話說透：
**「檢查產物，不是檢查工具。」**

超過 `fragment_bp_max` 時做 Gibson 片段切分，並一併寫出廠商訂購 CSV
（同一批封存鹼基的第四種形狀——因為**重新打字正是序列與標籤脫鉤的地方**）。

### Stage 6 — DIFF

與先前的 `.gb` 比對，報告長度差、相異位點數、第一個差異位置。

---

## 7. check_design.py：完全不同的另一半

這支工具值得單獨講，因為它和雜湊毫無關係。它的 docstring 寫明對象是
「一個被叫去『做一個建構』、還不知道基因前面需要核糖體結合位點的十四歲 iGEM 隊員」。

引擎會很樂意組出有這些問題的建構並封存它，因為引擎檢查的是「DNA 是否是你**說的**那樣」，
而不是「你說的那樣是否有生物學意義」。`check_design.py` 補上後者：

- 建構開頭不是 promoter → PROBLEM
- 編碼基因前面沒有 RBS → PROBLEM（含「你會得到一個看起來像基因壞掉的結果」的解釋）
- 最後一個基因後面沒有 terminator → PROBLEM
- 佔位符 seal 區塊（`PASTE_FROM_add_part`、length 0）→ PROBLEM
- 佔位符 role（`SET_THIS`）→ PROBLEM
- RBS 後面不是基因、重複使用部件、多 promoter 無 terminator → WORTH A LOOK

每一項都給三行：**看到什麼 / 為什麼重要 / 該怎麼做**。而且一次把所有問題報完
（`Report` 類的註解：「報一個問題、被修掉、再報下一個，是初學者損失一個下午的方式」）。

兩個設計細節很值得學：

1. `ori` 與 `marker` 在 `BACKBONE` 集合裡被豁免「列出但未使用」的警告——因為它們本來就在骨架上、
   刻意不在 `architecture.order` 裡。註解：「假警報是檢查器教人忽略它的方式。」
2. 佔位符檢查是後來補的，因為原本只檢查 seal 區塊「是否存在」，於是初學者打開的第一份模板
   會回報「nothing to report」，同時帶著 `PASTE_FROM_add_part` 和 length 0。
   「一個能通過所有檢查的佔位符，把『還沒填』變成『檢查過、沒問題』，這是最糟的讀法。」

---

## 8. Kagami：反向

### 8.1 它的定位宣告

README 第一段就先放棄一塊地盤：

> **Kagami 的優勢是稽核，不是註解。** 辨認質體裡有哪些部件已經被解決了（pLannotate、SnapGene、Benchling）。
> Kagami 的價值是疊在上面的 **QC 判定 + 原因 + 修法**——你在花掉贊助商 DNA 預算**之前**跑的那個檢查。

### 8.2 管線

```
kg_parse.parse()      → Record(seq, topology, features)   features = 建構對自己的「聲明」
kg_identify.identify() → list[Block]                        blastn 說這段「實際是」什麼
kg_audit.audit()      → list[Finding]                       比對聲明 vs 身分 + 一堆不需參考的檢查
kg_audit.verdict()    → FAIL / REVIEW — N to resolve / PASS — N notes
kg_bridge / kg_rebuild → 回到正向 Katana
```

輸入格式的寬容度是刻意的：`parse()` **按內容而非副檔名**分派，因為
「叫 .txt 的檔案裝 GenBank 的機率跟裝任何東西一樣高——而初學者的 .csv 常常是一格裡貼了一段序列」。
支援 FASTA / GenBank / csv / tsv / **xlsx（純標準庫解 zip+XML）** / 裸貼上。

多片段拼接會**明確宣告**，因為「用錯順序接起來會得到一個不同的建構，而它仍然會乾淨地通過稽核」。

### 8.3 五級判定——這是 2026-09-15 重做的核心

| 等級 | 意義 | 影響判定？ |
|---|---|---|
| **FAIL** | DNA 本身的缺陷（內部終止碼、空序列） | 是，直接 FAIL |
| **FLAG** | DNA 的真實性質，且在幾乎任何情境下都可行動（錯標、截斷、間距錯、GC/同聚物/重複） | 是，壓住 PASS |
| **NOTE** | 真實觀察，但重要性取決於讀者的組裝/宿主情境 | **否** |
| **SKIP** | 檢查沒有執行（沒選宿主） | 否，且**不計為發現** |
| **PASS** | 正面結果 | — |

嚴重度依情境決定，這是設計上最細緻的部分：

- 限制酶位點：**只有**你選的組裝方法的酶會切它時才是 FLAG，否則是 NOTE。
  （sfGFP 帶一個 SapI 位點——合成時毫不相干，Golden Gate/SapI 時是問題。）
- 宿主同源 >40 bp：**recA+** 宿主是 FLAG（可重組進染色體），**recA−** 克隆菌株只是 NOTE。
- 「沒選宿主」是 SKIP 而非問題——「我們沒檢查」絕不能讀成「我們檢查過、沒事」。

### 8.4 「identification 絕不無聲失敗」——最值得學的一次修補

`kg_identify.identify()` 接受一個 `status` dict，填入 `{"ran": bool, "reason": str}`。
原因寫在 `kg_audit.py:136-154` 和 `tests.py:445-452`：

> 由 Andrew Hao 對已發布 wiki 操作流程的獨立測試發現：**在沒有 BLAST+ 的機器上，
> Kagami 把刻意植入錯標的 demo 建構報成「PASS，clean to order」，exit 0，對跳過的步驟一字不提。**
> `identify()` 裡有兩條路徑把身分結果設為空清單然後繼續：BLAST+ 缺失、BLAST+ 拋例外。
> 下游 blocks 顯示「unidentified」——而這**也是**真正無匹配時的誠實用詞，兩者無法區分。
> 當時的測試套件裡零個測試提到 blast（任何大小寫），這就是它存活下來的原因。

修法有層次，而且分辨了三種不同狀況：

1. 無 BLAST+ 但檔案**有註解** → 用精確比對檢查它自己的聲明。錯標仍然抓得到，
   但截斷/單鹼基差異/片段抓不到。措辭：「只檢查了有註解的部件——未標記的區域可能藏著錯標」。
2. 無 BLAST+ 且檔案**無註解** → 什麼都沒比對。措辭保持直白：「這次稽核無法抓到錯標」。
3. BLAST+ **有裝但執行失敗** → 同一個洞，而且更難察覺。具名報告例外，不吞掉。

三種情況都是 **FLAG 而非 SKIP**：SKIP 是給使用者**主動不做**的檢查（沒選宿主）；
缺 BLAST+ 不是選擇退出——使用者要的是稽核，卻無聲地沒拿到它的核心一半。
而且 FLAG 把判定壓在 REVIEW，CLI exit code 是 5 而不是 0。

### 8.5 循環來源禁令（`kg_bridge.py`）

誘人的捷徑是：把每個 block 的位元組直接從貼進來的建構取出、雜湊、當部件封存。**Katana 禁止這件事。**

> 「從你正在稽核的那個建構裡封存一個部件，等於把一段未經驗證的序列洗成一段可信的序列
> ——正是 Katana 存在要殺掉的失效。」

所以 Kagami 產出兩個交接物，讓既有的正向工具去正確地做封存：

1. `--emit-intake` → 每個 block 一份請求，指名**要去取的一級來源**（Registry id / accession），
   絕不是建構的位元組。無匹配的 block 標為 **UNRESOLVED**——它在一級來源被辨明之前無法被封存。
2. `--emit-spec` → 草稿 Design Spec（**只有意圖，沒有鹼基**），已套用稽核的修正。

`kg_rebuild.py` 則把這條鏈自動化：`katana_init.py` → `add_part.py --registry`（逐部件從 Registry 新鮮取得）
→ 讀 LOCK → `katana_build.py`。它**以子程序方式驅動引擎自己的 CLI**，不 import 引擎任何東西
——所以 Kagami 保持解耦，而封存仍然來自每個部件的獨立一級來源。

`plan()` 的三種結果很乾淨：Registry 部件 `fetch`、已在你庫裡的 `reuse`、
designed/非 Registry 或未辨明的 → **blocker，停止重建**並逐部件給出具體指示。

### 8.6 參考集與信任分層

`kagami/refs/` 裝 **18,538** 個部件，來源分四層（`kg_refs._TIERS`，強者優先）：

| 前綴 | 意義 | tier |
|---|---|---|
| `parts-library …` | 本專案封存庫，建置時重算雜湊並比對 LOCK | 3 |
| `your library …` | `--library` 載入，同一道閘 | 3 |
| `iGEM Registry … uuid=… fetched=…` | api.registry.igem.org 即時取得，帶 uuid 與日期 | 2 |
| `SynBioHub … [snapshot 2017-04-03]` | SPARQL 鏡像，每列帶 per-part URI | 1 |
| `seed — verify vs …` | 手打、**尚未**對一級來源確認，最弱層且它自己說了 | 0 |

`build_refs.py` 的「讀取時不信任」閘很紮實：對每個庫部件重算 `seq_sha256`，要求它同時等於
LOCK 的值**和**檔名裡的 sha12，再重算 `LOCK.root` 對照 attestation log。任一不符即 fail-closed。
IP 邊界也是**檢查而非註解**：`class=designed` 且不在 `PUBLISHED_DESIGNED` 清單中的部件被拒絕。

兩個經過實測的過濾決定：

- **複合裝置必須排除。** 2026-09-15 量測：把目錄從 60 擴到 126 讓某個建構分解得**更差**。
  `BBa_I746909`（「T7 promoter 驅動的 sfGFP」，IGEM:0000007 Generator）以 863 bp / 99% 勝過三個精確的原子命中，
  把 RBS + sfGFP + terminator 塌成一個 block，順帶帶走 RBS 間距與 ORF 檢查。
- **primer 必須排除**（569 個）。一個 ~20 bp 的實驗室工具會在它的標的處處匹配，把建構變成一團假命中。

`_tile()` 的排名因此**先看完整性**（`cov >= 0.97`）再看相似度，而不是只看 bitscore——
因為 bitscore 隨對位長度成長，端到端匹配的參考才是一次「辨認」，81% 匹配的是「某個更大東西的片段」。

---

## 9. 測試與 CI：它如何證明自己

這是整個專案最強的部分，也是它和「印出 verified 的工具」的分界。

### 9.1 `verify.py` — 嘗試破壞檢查器

```
1. Verifying every part against the manifest…
   SEALED — 30 parts verified (file+seq+filename+manifest), root 4fb2e30f…, no orphans.
2. Trying to break the checker, eight ways…
   PASS — baseline library verifies SEALED
   PASS — Gap4b: edited accession in row is caught
   PASS — Gap5: orphan file with no row is caught
   PASS — Gap5: missing sealed file is caught (fail-closed)
   PASS — Bonus: tampered file bytes are caught
   PASS — Gap2: id-only resolution raises
   PASS — Gap2: id+version resolves to the pinned row
   PASS — Gap2: wrong seq-sha pin raises
```

它的 docstring 說得很準：「第二步比第一步重要。任何人都能印出 verified。」

### 9.2 `test_determinism.py` — 五路證明中心主張

ORACLE 那些雜湊**不是為測試編出來的**，而是這支隊伍實際向合成廠商訂購過的建構的封存雜湊。
`pAP-Logic` 就是被合成出來的那段 DNA。

特別值得一提的是它**刻意不 pin** 部件庫 root，並在 `find_lock_root()` 的 docstring 裡解釋為什麼
——這個 bundle 出貨的是較大工作庫的**子集**，兩者 root 依構造就不同，pin 其中一個會讓所有不是他們的人測試失敗。
而且坦承「它一開始就是那樣寫的，pin 到私有庫的 root，在發布前對一個真實 bundle 跑套件時才被抓到」。
把 `--expect-root` 這個旗標存在的理由（works on my machine）寫進展示該旗標的測試裡，會很難看。

### 9.3 `.gitlab-ci.yml` — 三個刻意分開的 job

| job | 證明什麼 |
|---|---|
| `verify` | 庫完好，且檢查器仍抓得到竄改 |
| `determinism` | 每份 Spec 仍重建到記錄的封存雜湊，錯 pin / 竄改 manifest 仍被拒 |
| `minimal-deps` | **只裝 PyYAML** 也能工作——選用檔必須退化為大聲警告，絕不崩潰 |
| `kagami` | **沒有 blastn** 的映像——「那是陌生人實際擁有的機器」 |

`minimal-deps` 存在是因為另外兩個 job 把所有東西都裝了。「要知道那條性質是否還成立，唯一的方法就是不裝它們去跑。」

### 9.4 `.gitattributes` 本身就是一份事故報告

```
# 它不是假設性的，它出貨過：這個 repo 第一次公開 clone 在 Windows 機器上
# 30 個部件全部 30 個 file hash 失敗，因為封存它的工作目錄是用複製檔案組起來的，
# 不是 git checkout，所以轉換從來沒對我們發生過。
```

`core.autocrlf=true` 在 checkout 時把 LF 轉成 CRLF，於是磁碟上的位元組與被封存的位元組不同，
每個部件在**乾淨 clone 上、對一個什麼都沒改的讀者**都 file hash 失敗。
序列本身一路都是好的（`seq_sha256` 相符，行尾不改變鹼基）——但位元組封印正是該注意
「檔案在你腳下改變了」的那個檢查，而它被版本控制系統本身打敗了。

`*.bat text eol=crlf` 那條例外也有一段實測理由：`cmd.exe` 用位元組偏移 seek 一個 .bat，
在 `GOTO` 或 `CALL` 時按「每行都以 CRLF 結束」計算位置恢復執行。平坦腳本裡這個漂移無害，
所以這些啟動器長期是 LF 而沒人注意；它們現在含有標籤和 FOR 區塊裡的 GOTO
——而它的失敗方式是**執行錯誤的那一行**，而不是報錯。

---

## 10. 我實際執行的驗證結果

我在一個獨立 venv（`PyYAML==6.0.2`、`sbol3==1.2.0.post0`、`python-codon-tables==0.1.12`）
裡跑了全部測試，本機有 `blastn` / `makeblastdb`。

| 執行 | 結果 |
|---|---|
| `python3 verify.py` | **OK** — 30 parts verified，8/8 對抗性檢查通過 |
| `python3 test_determinism.py` | **ALL PASSED — 11 checks**。7 份 Spec 全部重現記錄雜湊；`pAP-Output` SKIP（Spec 不在此 bundle） |
| `kagami/tests.py` | **88 passed, 0 failed** |
| `katana_build.py specs/pSense-Nit.spec.yaml` | SEALED `796e94a0ea2452ed…`，與 oracle 相符；.gb round-trip 雜湊驗證通過；SBOL 3 已驗證寫出 |
| `katana_build.py specs/pAP-Logic.spec.yaml` | SEALED `1d99b7be2c513b19…`；CAI：HrpR 0.809、HrpS 0.964（與 Spec 註解的 0.963 相符） |
| `kagami.py audit examples/demo.gb --host …` | **REVIEW — 2 to resolve**，植入的錯標被抓到；~11 秒（18,538 個參考） |

**核心主張成立。** 這個引擎確實是決定性的、確實 fail-closed，而且確實是建造出該隊伍訂購的那些 DNA 的同一個引擎。

---

## 11. 我在閱讀與執行中發現的問題

以下每一項我都實際驗證過，附重現方式。按影響排序。

### 🔴 0. macOS Gatekeeper 拒絕執行下載下來的啟動器（目前正在造成失敗）

這一項排在 A 之前，因為它是唯一我能直接量測到、而且**正在**阻止團隊成員使用這個工具的原因。

`com.apple.quarantine` 這個擴充屬性由**下載的應用程式**（瀏覽器、Mail）加上。實測：

```
$ xattr -w com.apple.quarantine "0083;00000000;Safari;" run_kagami_gui.command
$ spctl -a -vv -t open --context context:primary-signature run_kagami_gui.command
  run_kagami_gui.command: rejected
  source=no usable signature
```

只加簽章不做公證也一樣（ad-hoc 簽章測試 → 仍 `rejected`；Developer ID 簽章但未公證的下載 App 被擋是 Apple 自 Catalina 起的既定政策）。

而 `run_kagami_gui.command:8-10` 的註解建議使用者用「Right-click → Open」繞過——**那個繞道在 macOS 15 Sequoia 已被 Apple 移除**，測試機為 macOS 27.0。檔案提供的剩餘替代方案是「在 Terminal 跑 `python3 kagami_gui.py`」。

**為什麼團隊自己重現不出來。** `git clone` **不會**設定 quarantine 屬性；只有瀏覽器下載會。

| 取得方式 | 誰 | 結果 |
|---|---|---|
| `git clone` | 開發者 | 正常執行 |
| 下載 .zip | 每個測試者 | **被 Gatekeeper 拒絕** |

這個模式在本 repo 已經發生過一次。`.gitattributes` 的註解記錄著：第一次公開 clone 在 Windows 上 30 個部件全部 file hash 失敗，「因為封存它的工作目錄是用複製檔案組起來的，不是 `git checkout`，所以轉換從來沒對我們發生過」。同一個病根：**開發者取得程式的路徑與使用者不同。**

**封鎖範圍（實測）。** Gatekeeper 的封鎖來自 LaunchServices（雙擊），不是 `exec`：

| 執行方式（檔案帶 quarantine） | 結果 |
|---|---|
| 雙擊 `.command` | 被擋 |
| `bash run_kagami.command` | **正常執行** |
| `./run_kagami.command` | **正常執行** |

從 Terminal 執行 shell script 不受影響，因為核心 exec 的是已簽章的 `/bin/bash`，腳本只是資料。（編譯過的二進位檔從 Terminal 執行的行為未能量測——測試機的 clang/SDK 損壞。）

**修法選項：**
1. **零成本**：文件改為指示從 Terminal 執行（`bash run_kagami_gui.command`），而不是雙擊。同時移除 `.command` 註解裡已失效的「Right-click → Open」建議。
2. **$99/年**：Apple Developer + Developer ID 簽章 + 公證（notarize）+ staple。三步都做完才會零對話框；只簽章不公證無效。建議用組織帳號而非個人 Apple ID（iGEM 團隊每年解散，帳號需交接；已 staple 的版本在會籍過期後仍可用）。
3. 網頁版：Gatekeeper 是下載下來的可執行檔的屬性，網頁不是，所以完全不觸發。

---

### 🔴 A. 建置引擎的完整性閘不覆蓋 provenance 欄位

`katana_build.verify_lock_root()` 把 root 算成 **`row_sha256` 欄位「照寫的樣子」的雜湊**
（`katana_build.py:188-193`），它**不會**從各欄位重算 `row_sha256`。
`verify_library_v2.py:32` 會（`K.row_sha256(r)`）。

後果：**只改 `source` 欄位（accession、座標）而不動 `row_sha256`，建置引擎完全看不到。**

實測（在 `/tmp` 的副本上，把 lacZ 的 `NCBI NC_000913.3:363231-366305(-)`
改成 `NCBI NC_000913.3:999999-999999(+)`，`row_sha256` 原封不動）：

```
=== katana_build.py ===
  LOCK.root self-consistent (4fb2e30f9d9efec7…)      ← 通過
  建置 exit code = 0                                  ← 完成並封存

=== verify_library_v2.py ===
BLOCK — 2 problem(s):
  - lacZ v1: row_sha256 MISMATCH (a trust field — source/version/class/outfile — was edited)
  - LOCK.root MISMATCH: file=4fb2e30f9d9e recomputed=603d811a929a
```

`--expect-root` 也抓不到，因為磁碟上的 root 沒變。

序列本身仍受保護（Stage 2 會抓鹼基變動），所以錯的**序列**不可能通過。
但錯的**記錄來源**可以無聲通過建置——而「一段序列與它的聲明脫鉤」正是這個專案存在要防的那一類漂移。
`test_seal_gaps.py` 的 Gap4b 測試證明了這個檢查有效，但只在 `verify_library_v2.py` 裡，
那是你必須記得另外去跑的工具。

**修法**：`verify_lock_root` 裡把 `row["row_sha256"]` 換成從欄位重算的值（`katana_lock.row_sha256(row)`）。
約一行，而且 `katana_lock.py` 已經有這個函式。

### 🔴 B. Spec 只能 pin 每個部件的「最新版本」

`resolve_parts`（`:231-234`）按 id 掃 LOCK，保留**版本號最大**的那一列，然後只拿 pin 去比對那一列。

實測（把 `pAP-Logic` 的 `HrpS.Ec-opt` pin 從 v3 改回庫中確實存在的 v2）：

```
BLOCK Stage-1: part 'HrpS.Ec-opt' pin cc3f6c1ec6ef ≠ LOCK 5093ea792057
       Your Spec is pinned to one version of this part; your library
       holds a different one. One of them has moved on.
       → then update the seal block in your Spec to match it.
```

這與 `ARCHITECTURE.md` 的承諾直接矛盾：

> Parts are **immutable**. … History is append-only, so **a build from last month can still be reproduced.**

一旦某個部件有了新版本，**上個月的 Spec 就無法再重建了**——即使舊部件檔還在、
Spec 的 `seal.lib` 明確指名了它（`:258` 的 `gb_path = LIB / lib_file` 本來就會找到正確的檔案）。
而錯誤訊息給的建議是「把 Spec 的 seal 區塊改成符合庫」，那會**改變建構**。

這在 `pAP-Logic` 上是真實的：`HrpS.Ec-opt` 有 v1/v2/v3，`RBS_lldR_strong` 有 v1/v2/v3。
v5 到 v7 那幾版 Spec 今天都建不起來。

**修法**：pin 存在時，按 (id, pin) 或 (id, seal.lib) 解析，而不是按 max(version) 解析。
`katana_lock.resolve()` 已經是正確的語意（要求明確版本、拒絕 id-only），引擎沒有用它。

### 🟡 C. `LOCK.root.log` 被讀取、被文件描述，但沒有任何東西寫它

| 位置 | 做什麼 |
|---|---|
| `katana_lock.py:11` | 文件宣稱它「保存 root 的 append-only 歷史（輕量 attestation，無金鑰）」 |
| `verify_library_v2.py:59-63` | 若存在，檢查當前 root 是 log 的最後一項 |
| `kagami/build_refs.py:314` | 比對重算的 root 與「最後被 attest 的 root」 |
| `kagami/README.md:121` | 把它列為 fail-closed 閘的一部分 |

**沒有任何檔案寫入它**，而且它不存在於出貨的庫中（`find . -name 'LOCK.root*'` 只有 `LOCK.root`）。
`add_part.py:507` 只寫 `LOCK.root`。

所以這整層 attestation 是被文件化、被檢查、卻缺席的：兩個檢查都無聲降級為 no-op
（`build_refs.py` 至少會印「no LOCK.root.log to compare — per-part gate only」，`verify_library_v2.py` 不會說）。

### 🟡 D. Kagami 的同義參考 tie-break 讓正規部件輸給任意同義詞

這個比較微妙，而且**直接影響那個招牌 demo**。

實際跑 `kagami.py audit examples/demo.gb`：

```
36-47  +  rbs  K783051  [100.0% id, 100% cov]  claim="B0032"  (= 8 other refs: B0034, J34801, J70591 ...)

[FLAG] identity-mislabel  Block labelled "B0032" is actually K783051 (BBa_K783051)
       → fix: Re-label to K783051, or swap in the real B0032 sequence ...
```

錯標**被抓到了**，課程還在。但：

1. 報出來的名字是 **K783051**，不是 `README.md` / `make_demo.py` / `tests.py` 都說的 **B0034**。
2. 有 9 個參考共用 `AAAGAGGAGAAA` 這段序列。`_tile()` 的 tie-break 是
   `(cov>=0.97, pident, tier, bit)`——四項全部相等，於是贏家由 blast 輸出順序決定。
3. **而 `B0034` 的 tier 是 0，九個裡最低**，因為它是 `HAND_SEED` 條目（`seed — verify vs …`）。
   八個 SynBioHub 同義詞全是 tier 1。那個刻意設計來「偏好可信來源」的分層機制，
   在正規部件是手打種子時，**系統性地把它排到最後**。
4. 最關鍵的解釋因此丟失：`kg_audit.py:229-237` 那段「強度等級不同 → 表現量會明顯更強」
   只在匹配到的參考有 `variant` 時才觸發。`K783051` 的 `variant` 是 `None`，
   `B0034` 的是 `'strong'`。**「這是強 RBS 冒充弱 RBS」這句話，在實際執行中不會印出來。**
5. `tests.py` 的測試 1 通過，是因為它把 `REFERENCE_PARTS` 縮到 `_PIN` 那 14 個——
   在那個小集合裡只有 `B0034` 帶這段序列。這個 pin 本身是對的決定（測試應該測 Kagami 而不是目錄），
   但它的副作用是：**完整目錄下的真實行為沒有任何測試覆蓋。**

修法方向：tie-break 加一條「偏好有 `variant`/`role` 註記的參考」，或把 `B0034`、`J23100` 等正規部件
從 `HAND_SEED` 升級為真正取得的 Registry 列（`build_refs.py --registry-bulk` 本來就會做，
只是 `HAND_SEED` 在 `:421-426` 以「已有則跳過」的方式加入，而那 9 個同義詞不含 id `B0034`）。

### 🟡 E. bundle 裡已經有 MG1655 基因組，正向建置還是報 SKIPPED

`kagami/genomes/MG1655_ecoli_NC_000913.3.fna`（4.7 MB）是**受版控出貨的**。
但 `katana_drylab.py:90` 只看 `parts-library/ref_genomes/`：

```python
genome = (ref_parts.parent / "ref_genomes" / gfile) if (ref_parts and gfile) else None
```

而 `.gitignore` 排除 `parts-library/ref_genomes/`。所以：

```
WARN Stage-4b: OFF-TARGET SKIPPED - no genome here for host E_coli_MG1655.
               NOT enforced this run. Fetch one with: python3 get_genome.py
```

使用者被要求去下載一個 4.6 MB 的基因組，而**同一個 bundle 裡已經有同一個 accession 的同一個檔案**。
`README.md` 的「Genomes are large… and there is no correct set to bundle」理由完全成立，
但它已經被 Kagami 那一側違反了，而兩側不互通。

### 🟡 F. README 裡的 Windows BLAST+ 安裝指令含有實際的 backspace 位元組

`README.md` 是整個 repo 裡唯一含 **0x08（backspace）** 的檔案——3 行、共 6 個：

```
127: curl.exe -L -o "$env:TEMP^Hlast.exe" https://…/ncbi-blast-2.17.0+-win64.exe
135: $d="$env:LOCALAPPDATA^Hlast"; … +";$d^Hcbi-blast-2.17.0+^Hin","User")
```

原本應該是 `"$env:TEMP\blast.exe"`、`"$env:LOCALAPPDATA\blast"`、`$d\ncbi-blast-2.17.0+\bin`。
某個環節把 `\b` 當成轉義序列處理掉了（`\b` → 0x08），`\n` 也吃掉了一個反斜線。

這不是顯示假象，檔案裡確實是那些位元組（`LC_ALL=C tr -dc '\010' < README.md | wc -c` → 6）。
後果：**那兩條 PowerShell 一行指令對它們唯一的目標讀者（沒有管理員密碼的 Windows 學生）是壞的。**
以這個 repo 在其他地方對「讀者實際會複製的那一個東西」的講究程度（`tests.py` 測試 20 專門守護
BLAST+ 連結不腐壞），這個落差特別可惜。

### 🟢 G. `--expect-root "$(cat LOCK.root)"` 在 POSIX shell 上會失敗

`LOCK.root` 與 `LOCK.tsv` 是 **CRLF** 行尾（`.gb` 部件檔是 LF）。這本身無害——
所有庫內讀取者都 `.strip()`，而且 `.gitattributes` 的 `-text` 正確地保護了這些位元組。

但 `$(cat …)` 只剝除尾端的 `\n`，不剝 `\r`。於是 README 與 ARCHITECTURE 都在催你做的那件事
（「Pin your builds in CI」）最自然的寫法會失敗，而訊息把兩邊都截成 16 字，看起來**完全相同**：

```
BLOCK: LOCK.root mismatch: library=4fb2e30f9d9efec7… pinned=4fb2e30f9d9efec7… (wrong or stale library)
```

`--expect-root "$(tr -d '\r' < …/LOCK.root)"` 就通過了。
建議：`verify_lock_root` 對 `pinned` 也做 `.strip()`，並在訊息中顯示長度或完整雜湊。

### 🟢 H. 回文限制酶位點被重複計數

`find_re_sites`（`:439`）對正股與反股各跑一次 `finditer`。`RE_SITES` 裡 7 個酶中有 5 個是回文
（EcoRI `GAATTC`、XbaI `TCTAGA`、SpeI `ACTAGT`、PstI `CTGCAG`、NdeI `CATATG`），
它們的反向互補等於自己：

```python
find_re_sites("AAAGAATTCAAA", ["EcoRI"])
→ [('EcoRI', 3, 'fwd'), ('EcoRI', 3, 'rev')]     # 同一個位點，兩筆
```

只影響 BLOCK 訊息裡的計數（「2 blocking issue(s)」而實際是 1 個位點），不影響是否阻擋。

### 🟢 I. 文件與程式不同步之處

| 位置 | 文件說 | 實際 |
|---|---|---|
| `README.md`「Installing BLAST+」 | 「The check shells out to BLAST+」（指 Stage-4b off-target） | `katana_drylab.py:114` **直接呼叫** `B.fallback()`，純 Python，從不呼叫 `real_blast`。`ARCHITECTURE.md` 誠實說明是純 Python seed-and-extend。那段 BLAST+ 安裝說明其實是 Kagami 需要的，卻放在 Katana off-target 的小節底下 |
| `kagami/README.md:107` | 「currently **25 public parts**」 | **18,538**（`grep -c '^>' refs/reference_parts.fasta`） |
| `kagami/README.md:160` | 「`tests.py` **11** self-contained checks」 | **88** |
| `kagami/refs/ATTRIBUTION.md` 重建步驟 | `build_synbiohub_refs.py`、`convert_synbiohub_refs.py` | **兩個檔案都不在 repo 裡**，所以「Nothing here is hand-edited. To reproduce:」那段無法執行 |
| `ARCHITECTURE.md` SBOL 小節 | 「reference part → `wasDerivedFrom` 一個可解析 URI」 | `_source_uri` 只認得 `registry`/`part`/`accession`。`source: {db: Addgene, plasmid: …}`、`{db: Cello_UCF, ucf: …}`、`{note: …}` 都回傳 `None` → **該部件沒有任何 provenance 邊**。實測 `pAP-Logic`：12 個部件 Component，4 個 derived + 5 個 generated，**3 個無邊**（ALPaGA、ECK120033736、L3S2P55）。自由文字描述仍帶著來源（`_provenance_note` 泛用地輸出所有鍵），但機器可追的那條邊缺席且無警告 |
| `README.md` | 「deliberately corrupts a scratch copy **eight ways**」 | 8 項**檢查**：1 個 baseline（非破壞）+ 4 個實際破壞 + 3 個 resolver 行為檢查 |

另外：`class=designed` 但沒有 `design_record` 的部件（如 `pSense-Nit` 裡的 `RBS_sfGFP_med`）
在 SBOL 中兩條邊都拿不到——實測該建構 4 個 Component 只有 3 個 `wasDerivedFrom`、0 個 `wasGeneratedBy`。

### 🟢 J. 小瑕疵

- `kagami/build_refs.py:195-196`：`time.sleep(0.4)` 重複兩行（註解也重複），實際節流 0.8 秒。
- `katana_build.py:231-234`：`int(lver)` 對非數字版本號會拋 `ValueError`，不是 BLOCK 訊息。
- `kagami_gui.py` docstring 提到 `PASS / CONDITIONAL / FAIL`，程式用的是 `REVIEW`。
- `kagami/README.md` 的 verdict 說明也還寫 `CONDITIONAL`（exit code `1 / 5 / 0` 是對的）。

---

## 12. 評價：這個專案做對了什麼

撇開上面那些，這份程式碼有幾個特質在學生專案裡非常罕見，值得明確指出。

**1. 註解寫的是「為什麼」，而且往往是一次事故報告。**
整個 repo 的註解幾乎不解釋程式在做什麼（程式自己說得清楚），而是解釋**為什麼是這樣**，
並且常常附上日期、發現者、以及當時那個「顯而易見的修法」為什麼是錯的。例如
`AGENTS.md` 規則 4 的那段 2026-09-08 事故：驗證器標出一個孤兒部件檔，旁邊就放著一列準備好、
還沒合併的 manifest 列。合併它是顯而易見的修法，十秒鐘的事。它也是錯的——那個檔案的*序列*
雜湊成一個值，而它的*檔名*和那列準備好的資料都聲稱另一個值。同長度、不同鹼基。
合併會把一個假聲明永久寫進 manifest，而且從此永遠驗證通過。

**2. 它系統性地分辨「沒檢查」與「檢查過沒問題」。**
這是整份程式碼最一致的主題，而且在五個不同層次上實作：
Stage-4b 的 `NOT enforced this run`、Kagami 的 `SKIP` 等級、`identify_status` 的 `ran` 旗標、
`kg_registry` 把 `RegistryUnavailable` 與「部件不存在」分成兩個不同的回傳、
`write_json` 的 `identification_ran` 欄位（因為「消費這份 JSON 的 pipeline 否則無法分辨
空的 identity 欄位是『沒有參考匹配』還是『從來沒問』」）。

**3. 「檢查產物，不是檢查工具」被真的執行。**
`add_part.py` 寫完檔案後重讀、重算、不符就刪檔。`katana_build.py` Stage 5 重讀寫出的 `.gb`。
`katana_sbol.py` 寫完後重讀位元組並斷言它是合法 UTF-8（因為 `Document.write()` 走平台預設編碼，
在 cp1252 的 Windows 上一個非 ASCII 字元就產生一個「本機解析正常、對其他所有人都壞掉」的檔案
——他們短暫出貨過這個 bug，來源是這個模組自己描述文字裡的一個 em dash）。

**4. 錯誤訊息把讀者當成需要下一步的人，而不是需要被告知失敗的人。**
每個 BLOCK 都附上可以直接貼的指令。`get_genome.py` 甚至會在你下載完一個基因組後，
掃描旁邊的 Spec，只在**確實有 Spec 使用該宿主**時才承諾 SKIPPED 警告會消失
——因為無條件那樣說，在讀者選了範例不用的 chassis 時是個謊言，會送他們去跑一個
下載完 5 MB 之後仍然報 SKIPPED 的建置。

**5. 它知道自己不做什麼，並且明說。**
`README.md` 和 `ARCHITECTURE.md` 各有一個「What this does not do」小節：不設計任何東西、
不是組裝規劃器、不取代定序、測試測的是軟體而不是你的生物學。
Kagami 更直接放棄註解這塊地盤給 pLannotate / SnapGene。這種邊界感讓剩下的主張可信。

**最能說明這個專案品質的一句話**，來自 `test_determinism.py` 的 docstring：

> 不要為了讓測試通過而編輯這些雜湊：這裡的不符意味著引擎變了，而那正是這個測試要抓的東西。

---

## 13. 建議的處理順序

| 優先 | 項目 | 工作量 |
|---|---|---|
| 0 | **0** — Gatekeeper：文件改為從 Terminal 執行，並移除已失效的「右鍵 → 打開」建議 | 即刻（零成本） |
| 1 | **A** — `verify_lock_root` 改用重算的 `row_sha256` | ~1 行（函式已存在） |
| 2 | **B** — 按 pin / `seal.lib` 解析部件版本，而非 max(version) | ~10 行；另修 `ARCHITECTURE.md` 的承諾或程式二者之一 |
| 3 | **F** — 修掉 README 裡的 6 個 backspace 位元組 | 即刻 |
| 4 | **D** — tie-break 偏好帶 `variant`/`role` 的參考；補一個完整目錄下的 demo 測試 | 中 |
| 5 | **E** — `katana_drylab` 也去找 `kagami/genomes/` | ~5 行 |
| 6 | **C** — 讓 `add_part.py` 真的寫 `LOCK.root.log`，或把它從文件與檢查中移除 | 小 |
| 7 | **G / H / I / J** — pin 的 `.strip()`、回文去重、文件數字更新 | 小 |

其中 **A 與 B 值得優先**，不是因為它們現在造成了壞結果，而是因為它們是**這個專案自己的標準**
所瞄準的那兩類失效：A 讓一個聲明可以與它的序列脫鉤而通過建置；
B 讓「append-only 所以可重現」這個承諾在實務上不成立。
其餘都是整理工作。

---

*報告產出：讀完 94 個受控檔案 + 在獨立 venv 中執行 `verify.py`、`test_determinism.py`、
`kagami/tests.py`、兩次完整建置、一次 Kagami 稽核，以及五項針對性的重現實驗。*
