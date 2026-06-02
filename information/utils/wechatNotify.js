const https = require('https');
const url = require('url');

class WechatWorkNotify {
  constructor(webhookUrl) {
    this.webhookUrl = webhookUrl;
  }

  sendMarkdown(title, content) {
    return new Promise((resolve, reject) => {
      const body = JSON.stringify({
        msgtype: 'markdown',
        markdown: {
          title: title,
          content: content
        }
      });

      const parsedUrl = url.parse(this.webhookUrl);
      const options = {
        hostname: parsedUrl.hostname,
        port: 443,
        path: parsedUrl.path,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body)
        }
      };

      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          try {
            const result = JSON.parse(data);
            if (result.errcode !== 0) {
              console.error('企业微信通知失败:', result.errmsg);
              resolve(false);
            } else {
              resolve(true);
            }
          } catch (e) {
            console.error('解析企业微信响应失败:', e.message);
            resolve(false);
          }
        });
      });

      req.on('error', (error) => {
        console.error('企业微信通知异常:', error.message);
        resolve(false);
      });

      req.write(body);
      req.end();
    });
  }
}

module.exports = WechatWorkNotify;