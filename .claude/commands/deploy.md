# /deploy

引数: `$ARGUMENTS` (コンポーネント名。例: `ticket-service` または `mcp-servers/stackoverflow`)

指定されたコンポーネントをECRにビルド&プッシュする。

## 実行手順

1. **AWS環境確認**
   ```bash
   aws sts get-caller-identity
   ```
   アカウントIDとリージョンを確認。失敗したら中断してユーザーに報告。

2. **ECRリポジトリ確認・作成**
   ```bash
   aws ecr describe-repositories --repository-names agora-$ARGUMENTS --region us-east-1
   ```
   存在しない場合は作成が必要である旨をユーザーに確認してから:
   ```bash
   aws ecr create-repository --repository-name agora-$ARGUMENTS --region us-east-1 --image-scanning-configuration scanOnPush=true
   ```

3. **Dockerビルド** (ARM64)
   ```bash
   make build img=$ARGUMENTS
   ```

4. **ECRログイン・タグ・プッシュ**
   ```bash
   make deploy img=$ARGUMENTS
   ```
   ※ `make deploy` は承認が必要なコマンドのため、実行前にユーザーに確認を取る。

5. **AgentCore Runtime登録** (実装済みの場合)
   CDKスタックが存在する場合は `cdk deploy` で更新する。
   まだCDK未実装の場合はその旨を報告して終了。

## 注意事項

- `make deploy` は `docker push` を含むため**必ずユーザーに確認してから実行する**
- デプロイ先を間違えないようにアカウントIDをユーザーに必ず表示する
