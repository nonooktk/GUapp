-- docker-compose.yml 用の初期化 SQL（初回起動時に /docker-entrypoint-initdb.d から実行される）
-- guapp（開発用）は MYSQL_DATABASE で作られるので、ここでは IT 用の guapp_test を作り、guapp ユーザーに権限を付与する。
CREATE DATABASE IF NOT EXISTS guapp_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
GRANT ALL PRIVILEGES ON guapp_test.* TO 'guapp'@'%';
FLUSH PRIVILEGES;
