/**
 * 就活管理ツール用のローカルプロキシ
 * 使い方: node 就活管理-proxy.js
 * ブラウザから http://localhost:3456 へ Claude API を中継します
 */
const http = require("http");
const https = require("https");

const PORT = 3456;

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

function callClaude(apiKey, companyName) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      model: "claude-sonnet-4-5",
      max_tokens: 1200,
      messages: [
        {
          role: "user",
          content: `日本の企業「${companyName}」について、就職活動中の学生向けに以下を簡潔に日本語でまとめてください。不明な点は推測と明記してください。

回答は必ず次のJSON形式のみで返してください（説明文やマークダウンは不要）:
{"overview":"企業概要（2〜3文）","business":"主な事業内容（2〜3文）","shukatsuFeatures":"就活における特徴・選考傾向・働き方など（3〜5行）"}`,
        },
      ],
    });

    const options = {
      hostname: "api.anthropic.com",
      path: "/v1/messages",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "Content-Length": Buffer.byteLength(payload),
      },
    };

    const apiReq = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) {
            reject(new Error(parsed.error.message || "APIエラー"));
            return;
          }
          const text = parsed.content?.[0]?.text || "";
          const match = text.match(/\{[\s\S]*\}/);
          if (!match) {
            reject(new Error("AIの応答をJSONとして解析できませんでした"));
            return;
          }
          resolve(JSON.parse(match[0]));
        } catch (err) {
          reject(err);
        }
      });
    });

    apiReq.on("error", reject);
    apiReq.write(payload);
    apiReq.end();
  });
}

const server = http.createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Api-Key");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "POST" && req.url === "/api/company-info") {
    try {
      const body = await readBody(req);
      const { companyName } = JSON.parse(body || "{}");
      const apiKey = req.headers["x-api-key"];

      if (!apiKey) {
        res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ error: "APIキーが設定されていません" }));
        return;
      }
      if (!companyName?.trim()) {
        res.writeHead(400, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ error: "企業名を入力してください" }));
        return;
      }

      const result = await callClaude(apiKey, companyName.trim());
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify(result));
    } catch (err) {
      res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: err.message || "サーバーエラー" }));
    }
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: "Not found" }));
});

server.listen(PORT, () => {
  console.log(`就活管理プロキシ起動: http://localhost:${PORT}`);
  console.log("就活管理.html を開いたまま「AIで企業情報を取得」を使えます");
});
