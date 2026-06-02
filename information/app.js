require('dotenv').config();
const EmailMonitor = require('./utils/emailMonitor');
const emailAccounts = require('./config/emailAccounts');

const monitors = [];

async function startMonitors() {
  console.log('🚀 邮箱监控服务启动中...');
  console.log('📧 加载邮箱配置:', emailAccounts.length, '个账户');
  
  for (const account of emailAccounts) {
    if (!account.email || !account.password) {
      console.log(`⚠️ 跳过未配置的账户: ${account.name}`);
      continue;
    }
    
    try {
      const monitor = new EmailMonitor(account);
      await monitor.connect();
      monitors.push({ account, monitor });
      console.log(`✅ 成功连接: ${account.name} (${account.email})`);
    } catch (error) {
      console.error(`❌ 连接失败: ${account.name} - ${error.message}`);
    }
  }
  
  console.log('📡 监控服务已启动，等待新邮件...');
}

startMonitors();

process.on('SIGINT', () => {
  console.log('\n📤 正在关闭监控服务...');
  monitors.forEach(({ account, monitor }) => {
    monitor.disconnect();
    console.log(`🔌 已断开: ${account.name}`);
  });
  process.exit(0);
});