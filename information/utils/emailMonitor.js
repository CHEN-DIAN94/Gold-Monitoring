const Imap = require('imap');
const { simpleParser } = require('mailparser');
const WechatWorkNotify = require('./wechatNotify');

// 修复：确保 dotenv 已加载
require('dotenv').config();

const wechatNotify = new WechatWorkNotify(process.env.WECHAT_WEBHOOK_URL);

class EmailMonitor {
  constructor(account) {
    this.account = account;
    this.imap = null;
    this.isConnected = false;
  }

  connect() {
    return new Promise((resolve, reject) => {
      // 修复：验证密码是否存在
      if (!this.account.password) {
        reject(new Error(`[${this.account.name}] 密码未配置，请在 .env 文件中设置对应的密码环境变量`));
        return;
      }

      this.imap = new Imap({
        user: this.account.email,
        password: this.account.password,
        host: this.account.imapHost,
        port: this.account.imapPort,
        tls: this.account.imapTls,
        tlsOptions: { rejectUnauthorized: true }  // 修复：启用证书验证
      });

      this.imap.once('ready', () => {
        this.isConnected = true;
        console.log(`📧 [${this.account.name}] IMAP连接成功`);
        this.monitorInbox();
        resolve();
      });

      this.imap.once('error', (err) => {
        console.error(`❌ [${this.account.name}] 连接失败:`, err.message);
        reject(err);
      });

      this.imap.once('end', () => {
        this.isConnected = false;
        console.log(`🔌 [${this.account.name}] 连接已断开`);
      });

      this.imap.connect();
    });
  }

  monitorInbox() {
    this.imap.openBox('INBOX', false, (err, box) => {
      if (err) {
        console.error(`❌ [${this.account.name}] 打开收件箱失败:`, err);
        return;
      }

      console.log(`📡 [${this.account.name}] 开始监控收件箱...`);

      this.imap.on('mail', (numNewMessages) => {
        console.log(`📨 [${this.account.name}] 收到 ${numNewMessages} 封新邮件`);
        this.fetchLatestEmail();
      });

      this.imap.on('expunge', (seqno) => {
        console.log(`🗑️ [${this.account.name}] 邮件 ${seqno} 已删除`);
      });
    });
  }

  async fetchLatestEmail() {
    this.imap.search(['UNSEEN'], (err, results) => {
      if (err || !results.length) return;

      const f = this.imap.fetch(results.slice(-1), { bodies: '' });

      f.on('message', async (msg) => {
        msg.on('body', async (stream) => {
          try {
            const parsed = await simpleParser(stream);
            const emailInfo = {
              from: parsed.from?.text || 'Unknown',
              subject: parsed.subject || 'No Subject',
              date: parsed.date?.toLocaleString() || new Date().toLocaleString(),
              snippet: parsed.text?.substring(0, 100) + '...' || 'No content'
            };
            
            console.log(`📩 [${this.account.name}] 新邮件: ${emailInfo.subject}`);
            await this.sendWechatNotification(emailInfo);
          } catch (parseErr) {
            console.error('❌ 解析邮件失败:', parseErr);
          }
        });
      });

      f.on('error', (fetchErr) => {
        console.error('❌ 获取邮件失败:', fetchErr);
      });
    });
  }

  async sendWechatNotification(email) {
    const message = `📧 **新邮件提醒**\n\n**邮箱**: ${this.account.name}\n**发件人**: ${email.from}\n**主题**: ${email.subject}\n**时间**: ${email.date}\n**摘要**: ${email.snippet}`;
    
    const success = await wechatNotify.sendMarkdown('新邮件通知', message);
    if (success) {
      console.log('✅ 企业微信通知发送成功');
    } else {
      console.log('❌ 企业微信通知发送失败');
    }
  }

  disconnect() {
    if (this.imap) {
      this.imap.end();
    }
  }

  isRunning() {
    return this.isConnected;
  }
}

module.exports = EmailMonitor;