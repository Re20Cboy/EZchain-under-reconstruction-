"""
VPB测试运行器

运行所有VPB相关测试的便捷脚本。
"""

import sys
import os
import subprocess

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_simple_tests():
    """运行简化测试套件"""
    print("=" * 80)
    print("运行VPBPairs简化测试套件")
    print("=" * 80)

    result = subprocess.run([
        sys.executable,
        os.path.join(os.path.dirname(__file__), "test_vpb_pairs_simple.py")
    ], capture_output=False, text=True)

    return result.returncode == 0

def run_comprehensive_tests():
    """运行完整测试套件"""
    print("=" * 80)
    print("运行VPBPairs完整测试套件")
    print("=" * 80)

    result = subprocess.run([
        sys.executable,
        "-m", "pytest",
        os.path.join(os.path.dirname(__file__), "test_vpb_pairs_comprehensive.py"),
        "-v"
    ], capture_output=False, text=True)

    return result.returncode == 0

def main():
    """主函数"""
    print("VPB测试运行器")
    print("基于VPB设计文档的完整测试套件")

    # 首先运行简化测试
    simple_success = run_simple_tests()

    if simple_success:
        print("\n简化测试通过！")

        # 询问是否运行完整测试
        try:
            response = input("\n是否运行完整测试套件？(y/n): ").lower().strip()
            if response in ['y', 'yes', '是']:
                comprehensive_success = run_comprehensive_tests()

                if comprehensive_success:
                    print("\n" + "=" * 80)
                    print("🎉 所有测试通过！VPBPairs实现完全符合设计要求。")
                    print("=" * 80)
                else:
                    print("\n" + "=" * 80)
                    print("❌ 完整测试部分失败，但基础功能正常。")
                    print("=" * 80)
            else:
                print("\n跳过完整测试。")
        except KeyboardInterrupt:
            print("\n测试被用户中断。")
        except Exception as e:
            print(f"\n运行完整测试时出错: {e}")
    else:
        print("\n" + "=" * 80)
        print("❌ 简化测试失败，请检查基础实现。")
        print("=" * 80)

if __name__ == "__main__":
    main()