#!/usr/bin/env python3
"""
EZchain 多轮交易测试运行脚本
简化的多轮测试启动器，支持命令行参数
"""

import sys
import os

# Add the project root and current directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, current_dir)

from test_multi_round_real_account_transaction import run_multi_round_integration_tests

def main():
    """主函数"""

    # 设置编码以支持中文字符和emoji
    try:
        if sys.platform == "win32":
            # Windows下设置UTF-8编码
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            # 在Windows下设置环境变量以支持UTF-8
            os.environ['PYTHONIOENCODING'] = 'utf-8'
    except:
        pass

    print("🚀 EZchain 多轮交易测试启动器")
    print("=" * 50)

    # 解析命令行参数
    num_rounds = 20  # 默认5轮

    if len(sys.argv) > 1:
        try:
            num_rounds = int(sys.argv[1])
            if num_rounds <= 0:
                print("⚠️ 轮数必须大于0，使用默认值3")
                num_rounds = 3
            elif num_rounds > 10:
                print("⚠️ 轮数过多，限制在10轮以内")
                num_rounds = 10
        except ValueError:
            print("⚠️ 无效的轮数参数，使用默认值3")
            num_rounds = 3

    print(f"📊 计划执行 {num_rounds} 轮完整交易流程")
    print(f"💡 每轮包含: 创建→交易池→选择→区块→上链")
    print("=" * 50)

    # 运行多轮测试
    success = run_multi_round_integration_tests(num_rounds)

    # 退出
    exit_code = 0 if success else 1
    print(f"\n🏁 测试完成，退出码: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()