# 領収書 OCR 審査サンプル (CodexTest / AllLink)

ローカル環境（Windows 11/WSL(Ubuntu) 向け想定）で領収書画像を OCR し、抽出結果を保存・一覧・承認できる Web アプリです。2024/11 以降は社内ワークフロー統合ツール **AllLink** として、メール・PC・各種アカウント申請などの汎用フローも GUI で作成・承認できます。ログイン/申請/承認/ログアウトの操作ログを `data/logs/app.log` に記録し、通知・統計・エクスポート・API 連携にも対応します。

## 機能 (AllLink_V0.6)
AllLink_V0.6 で提供する主な機能は以下のとおりです。

1. **申請登録（財務会計フロー）**: 領収書画像をアップロードすると、日付/宛先/金額/登録番号を OCR で抽出し、申請者（初期値 XYY）、画像パスと一緒に SQLite DB へ保存。
2. **申請一覧**: これまでの申請をテーブルで表示。画像へのリンク付き。
3. **承認画面**: 申請ごとに領収書と抽出値を突合し、OK/NG とコメントを一括保存。最新の承認履歴を確認可能。
4. **ユーザー管理**: 管理者によるユーザー登録、権限（admin/user）管理、ログイン/ログアウト。
5. **監査ログ**: ログイン/ログアウト/申請/承認などの操作ログを `data/logs/app.log` に記録。
6. **社内フロー作成 (AllLink)**: `/flows` で GUI ベースのフロー作成・承認ルート設定が可能。財務会計フローに加え、メールアドレス・PC・iPad・社内システムアカウントなど任意のフローを追加。
7. **フロー別申請・承認**: フロー単位で申請登録、申請一覧、承認画面を用意し、登録データをフローごとに分離して表示。
8. **メール通知**: 申請・承認時に SMTP 経由で通知メールを送信。
9. **ダッシュボード**: 承認率や平均処理時間などの統計を `/dashboard` で可視化。
10. **API 連携**: `/api/submissions` や `/api/flows/{id}/requests` から JSON 取得が可能。
11. **エクスポート**: CSV（Excel）/PDF で申請一覧を出力。
12. **モバイル対応**: レスポンシブ UI によりスマホブラウザからの申請/承認が可能。

## 画面デザイン (Manus 風)
- **ニュートラルな配色**: 明るい背景と青系アクセントで、視認性と落ち着きを両立。
- **カード UI**: 情報ブロックは角丸＋シャドウで整理し、画面全体の階層を明確化。
- **ピル型ボタン/ステータス**: 操作・状態をコンパクトに識別できるように統一。
- **ヘッダーの情報密度**: ロゴ・説明・ナビ・ユーザー情報を上部に集約して、視線移動を最小化。

## システム機能詳細
各画面/機能の入出力と保存先を整理しています。

### 1. 認証/ユーザー管理
- **ログイン**: `/auth/login` でユーザー名・パスワードを認証。成功時にセッションを生成。
- **ログアウト**: `/auth/logout` でセッション破棄。
- **ユーザー登録**: 管理者のみ `/auth/register` で登録/権限設定が可能。
- **ログ記録**: 成功/失敗を `data/logs/app.log` に記録。

### 2. 財務会計フロー (領収書 OCR)
- **登録**: `/` で画像アップロード → OCR 抽出 → `data/app.db` に保存。
- **一覧**: `/submissions` で登録済み申請を検索・確認。
- **承認**: `/approvals` で OK/NG とコメントを一括保存。
- **画像保存**: `data/receipts/` に原本を格納し、DB は相対パスを保持。

### 3. 汎用フロー (AllLink)
- **フロー定義**: `/flows` でフロー名・承認ルートを GUI で登録。
- **申請**: `/flows/<flow_id>/requests/new` でフロー別申請を登録。
- **一覧**: `/flows/<flow_id>/requests` でフロー別の履歴を一覧表示。
- **承認**: `/flows/<flow_id>/approvals` でフロー別に承認可能。

### 4. 監査/トラッキング
- **操作ログ**: ログイン/申請/承認/ログアウトを `data/logs/app.log` に記録。
- **確認方法**: PowerShell なら `Get-Content data/logs/app.log -Tail 50` で直近を確認。

### 5. ダッシュボード (統計)
- **アクセス**: `/dashboard` で統計情報をカード表示。
- **指標**: 申請数、承認率、平均処理時間（時間単位）。

### 6. 通知 (メール)
- **送信タイミング**: 申請登録・承認保存の直後に通知。
- **設定**: `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_TO` を環境変数で指定。

### 7. エクスポート
- **領収書申請**: `/exports/submissions?format=csv|pdf`
- **汎用フロー申請**: `/exports/flows/<flow_id>?format=csv|pdf`
- **用途**: CSV を Excel で開けます。PDF は簡易スナップショット用途（日本語は `?` に置換される場合があります）。

### 8. API 連携
- **申請一覧 API**: `/api/submissions`
- **フロー申請 API**: `/api/flows/<flow_id>/requests`

## セットアップ (Windows 11, PowerShell)
以下は「誰がどこで何をどうやって実行し、成功をどう確認するか」を明示した手順です。

1. **前提を準備 (実行者: 開発者・場所: ローカル PC)**
   - [Python 3.11+](https://www.python.org/) をインストールし、セットアップ時に「Add python.exe to PATH」をオンにする。
   - [Tesseract OCR (UB Mannheim 版)](https://github.com/UB-Mannheim/tesseract/wiki) をインストールする。インストール先が PATH に入っていない場合は場所 (例: `C:\Program Files\Tesseract-OCR\tesseract.exe`) を控える。日本語対応のため `jpn` 言語データを含むパッケージを選択。

2. **コードを取得 (実行者: 開発者・場所: コード格納ディレクトリ)**
   ```powershell
   git clone <repository-url> CodexTest
   cd CodexTest
   ```

3. **仮想環境と依存関係 (実行者: 開発者・場所: `CodexTest` 直下)**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **環境変数を設定 (必要な人のみ・場所: PowerShell セッション)**
   - Tesseract を PATH に入れていない場合:
     ```powershell
     $env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
     ```
   - 管理者ユーザーの初期パスワードを変えたい場合:
     ```powershell
     $env:DEFAULT_ADMIN_PASSWORD="your-strong-password"
     ```
   - セッション暗号鍵を固定したい場合:
     ```powershell
     $env:SESSION_SECRET="random-hex-string"
     ```
   - メール通知を使う場合:
     ```powershell
     $env:SMTP_HOST="smtp.example.com"
     $env:SMTP_PORT="587"
     $env:SMTP_USER="smtp-user@example.com"
     $env:SMTP_PASSWORD="smtp-password"
     $env:SMTP_FROM="alllink@example.com"
     $env:SMTP_TO="finance@example.com"
     ```

5. **アプリを起動 (実行者: 開発者・場所: `CodexTest` 直下)**
   ```powershell
   uvicorn app.main:app --reload
   ```
   - ブラウザで `http://127.0.0.1:8000/` にアクセスし、画面が表示されれば起動成功。

6. **検証フロー (実行者: テスター・場所: ブラウザ)**
   1. **ログイン**: `/auth/login` で `admin` / `DEFAULT_ADMIN_PASSWORD` でサインイン。成功するとトップにリダイレクト。
   2. **申請登録**: トップで領収書画像をアップロードし送信。`/submissions` に登録された行が増えていれば成功。
   3. **承認**: `/approvals` で OK/NG を選び送信。直近の承認結果がカード下部に表示されれば成功。
   4. **ダッシュボード**: `/dashboard` で統計カードが表示されれば成功。
   5. **エクスポート**: `/exports/submissions?format=csv` を開き、CSV がダウンロードされれば成功。
   6. **ログアウト**: 画面のログアウトボタンを押す。再びトップへ戻り、ログイン画面が必要になる状態なら成功。
   7. **ログ確認**: 操作ログは `data/logs/app.log` に追記される。PowerShell で確認:
      ```powershell
      Get-Content data/logs/app.log -Tail 20
      ```
      - ログイン/ログアウト/申請/承認が「だれが (username)」「どのデバイス/IP」「いつ」「何をしたか」で記録されていることを確認。

7. **データの場所**
   - DB: `data/app.db` (SQLite)
   - 領収書画像: `data/receipts/`
- 操作ログ: `data/logs/app.log`

## 最終版まとめ (中文)
以下は**安装步骤**と**系统功能说明**の最終版要点です。

### 安装步骤 (Windows 11 / PowerShell)
1. **准备环境**: 安装 Python 3.11+，并勾选 “Add python.exe to PATH”；安装 Tesseract OCR（含日文语言包）。
2. **获取代码**:
   ```powershell
   git clone <repository-url> CodexTest
   cd CodexTest
   ```
3. **创建虚拟环境并安装依赖**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
4. **设置环境变量 (可选)**:
   ```powershell
   $env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
   $env:DEFAULT_ADMIN_PASSWORD="your-strong-password"
   $env:SESSION_SECRET="random-hex-string"
   ```
5. **启动服务**:
   ```powershell
   uvicorn app.main:app --reload
   ```
   浏览器访问 `http://127.0.0.1:8000/`，出现页面即启动成功。

### 系统功能说明 (详细版)
- **账号与权限**: 管理员可注册用户并设置角色（admin/user）。
- **财务会计流程**: 领收书上传 → OCR 抽取 → 申请存档 → 承认/拒绝。
- **通用流程**: 支持邮件/账号/设备等流程配置，自动生成申请/列表/承认页面。
- **审计日志**: 所有关键操作写入 `data/logs/app.log`，可按时间追溯。
- **邮件通知**: 申請与承认触发 SMTP 邮件提醒。
- **统计看板**: `/dashboard` 展示承认率与平均处理时间。
- **导出**: 支持 CSV（Excel）/PDF 导出。
- **API**: 提供 JSON 接口便于系统对接。

## Windows 11 で WSL (Ubuntu_AllLink) を用いた隔離環境構築
Windows 本体への影響を避けたい場合は、WSL 上に **Ubuntu_AllLink** という専用ディストリビューションを作成し、AllLink_V0.6 をセットアップしてください。以下は PowerShell からの手順です。

### 0. 事前確認
- PowerShell を「管理者として実行」する。
- 初回の WSL インストール後は PC の再起動と Linux ユーザー作成が必要。

### 1. WSL/Ubuntu をインストール
```powershell
wsl --install -d Ubuntu
```
- 再起動後に Ubuntu を開き、求められたら Linux ユーザー名とパスワードを作成。

### 2. Ubuntu_AllLink を作成 (隔離環境)
```powershell
wsl --export Ubuntu "$env:TEMP\\ubuntu_alllink_rootfs.tar"
wsl --import Ubuntu_AllLink "$env:USERPROFILE\\WSL\\Ubuntu_AllLink" "$env:TEMP\\ubuntu_alllink_rootfs.tar" --version 2
Remove-Item "$env:TEMP\\ubuntu_alllink_rootfs.tar"
```
- 作成後に **Ubuntu_AllLink** を起動し、Linux ユーザー名とパスワードを設定。

### 3. Ubuntu_AllLink 内で依存関係を導入
```powershell
wsl -d Ubuntu_AllLink -- sudo apt-get update -y
wsl -d Ubuntu_AllLink -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip git tesseract-ocr tesseract-ocr-jpn libtesseract-dev
```

### 4. ソース取得と仮想環境
```powershell
wsl -d Ubuntu_AllLink -- git clone https://github.com/xiaokainan/CodexTest.git ~/AllLink_V0_6
wsl -d Ubuntu_AllLink -- bash -lc "cd ~/AllLink_V0_6 && python3 -m venv .venv && . .venv/bin/activate && python -m pip install --upgrade pip && pip install -r requirements.txt && mkdir -p data/logs data/receipts"
```

### 5. アプリを起動
```powershell
wsl -d Ubuntu_AllLink -- bash -lc "cd ~/AllLink_V0_6 && . .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"
```
- ブラウザで `http://localhost:8000/` を開けば WSL 上のアプリにアクセス可能。

### 6. 自動化バッチ (推奨)
ルートにある `setup_wsl_alllink.bat` を管理者権限の PowerShell から実行すると、次を自動化します:

- WSL および Ubuntu の有無を確認し、未導入なら `wsl --install -d Ubuntu` でセットアップ（再起動が必要な場合あり）。
- Ubuntu から **Ubuntu_AllLink** を複製し、隔離環境を作成。
- Ubuntu_AllLink 内で Python/Tesseract/git などをインストール。
- リポジトリの clone または git pull。
- 仮想環境 `.venv` の作成と依存関係のインストール。
- データディレクトリ (`data/logs`, `data/receipts`) の作成。

再起動が必要になった場合は、再起動後にもう一度バッチを実行してください。起動は手順 4 と同じコマンドで行えます。

## 使い方
- **申請 (機能1)**: トップページから申請者（初期値 XYY）と領収書画像を選択して送信。OCR 抽出結果と画像パスが DB に保存されます。
- **一覧 (機能2)**: `/submissions` で申請履歴を確認。画像は `/receipts/...` から直接参照可能。
- **承認 (機能3)**: `/approvals` で各申請の画像と抽出値を確認し、OK/NG とコメントを入力して一括保存。最新の承認結果がカード下部に表示されます。
- **汎用フロー (機能6-7)**: `/flows` で新規フローを作成し、ステップごとの承認ルートを GUI で設定。各フローに対し「申請一覧」「承認」「新規申請」画面が自動生成されます。
- **ダッシュボード**: `/dashboard` で承認率・処理時間などの統計を確認。
- **エクスポート**: 申請一覧画面の CSV/PDF ボタンから出力。

## 補足
- データは `data/app.db` (SQLite) に保存されます。領収書画像は `data/receipts/` 配下へ保存されます。
- 既存 DB/画像を初期化したい場合は `data/app.db` と `data/receipts/*` を削除してください。
- OCR 精度は画像品質に依存します。読み取りに失敗した場合は承認画面でコメントを残して運用してください。
