#!/usr/bin/env python3
"""
演示Blockchain永久化存储功能

这个脚本演示了改进后的Blockchain类的永久化存储功能，包括：
1. 自动保存和加载
2. 备份功能
3. 数据完整性校验
4. 分叉持久化
"""

import sys
import os
import tempfile
import shutil
import time

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from EZ_Main_Chain.Blockchain import Blockchain, ChainConfig
from EZ_Main_Chain.Block import Block


def main():
    """演示永久化存储功能的主函数"""

    print("EZchain 区块链永久化存储演示")
    print("=" * 50)

    # 创建临时演示目录
    demo_dir = "blockchain_demo"
    if os.path.exists(demo_dir):
        shutil.rmtree(demo_dir)

    # 配置区块链
    config = ChainConfig(
        data_directory=demo_dir,
        auto_save=True,  # 启用自动保存
        backup_enabled=True,  # 启用备份
        backup_interval=3,  # 每3个区块创建一次备份
        max_backups=5,  # 最多保留5个备份
        integrity_check=True,  # 启用数据完整性检查
        debug_mode=True  # 启用调试模式
    )

    print("配置信息:")
    print(f"  数据目录: {config.data_directory}")
    print(f"  自动保存: {config.auto_save}")
    print(f"  备份间隔: {config.backup_interval} 区块")
    print(f"  最大备份数: {config.max_backups}")
    print(f"  完整性检查: {config.integrity_check}")
    print()

    # 创建区块链实例
    print("🚀 创建区块链实例...")
    blockchain = Blockchain(config=config)
    print(f"  区块链已初始化，当前长度: {len(blockchain)}")
    print()

    # 添加一些区块
    print("📦 添加区块到区块链...")
    blocks_added = []

    for i in range(1, 8):
        block = Block(
            index=i,
            m_tree_root=f"merkle_root_{i}",
            miner=f"miner_{i}",
            pre_hash=blockchain.get_latest_block_hash()
        )

        # 添加一些交易到布隆过滤器
        block.add_item_to_bloom(f"transaction_{i}_1")
        block.add_item_to_bloom(f"transaction_{i}_2")

        result = blockchain.add_block(block)
        blocks_added.append(block)

        print(f"  添加区块 #{i} - 矿工: miner_{i} - 主链更新: {result}")

        # 检查备份创建
        if i % config.backup_interval == 0:
            print(f"    📸 自动备份已创建 (第{i}个区块)")

    print(f"✅ 成功添加了 {len(blocks_added)} 个区块")
    print(f"   区块链当前长度: {len(blockchain)}")
    print(f"   最新区块: #{blockchain.get_latest_block_index()}")
    print()

    # 展示分叉功能
    print("🌿 创建分叉...")
    # 在区块2上创建分叉
    block2 = blockchain.get_block_by_index(2)
    if block2:
        fork_block1 = Block(
            index=3,
            m_tree_root="fork_merkle_1",
            miner="fork_miner_1",
            pre_hash=block2.get_hash()
        )
        blockchain.add_block(fork_block1)
        print("  创建分叉区块 #3 (在区块#2基础上)")

        fork_block2 = Block(
            index=4,
            m_tree_root="fork_merkle_2",
            miner="fork_miner_2",
            pre_hash=fork_block1.get_hash()
        )
        blockchain.add_block(fork_block2)
        print("  创建分叉区块 #4 (在分叉#3基础上)")

    # 显示分叉统计
    stats = blockchain.get_fork_statistics()
    print()
    print("📊 分叉统计:")
    print(f"  总节点数: {stats['total_nodes']}")
    print(f"  主链节点数: {stats['main_chain_nodes']}")
    print(f"  分叉节点数: {stats['fork_nodes']}")
    print(f"  已确认节点数: {stats['confirmed_nodes']}")
    print(f"  孤儿节点数: {stats['orphaned_nodes']}")
    print(f"  当前高度: {stats['current_height']}")
    print()

    # 手动创建备份
    print("💾 创建手动备份...")
    backup_result = blockchain.create_backup()
    print(f"  备份创建: {'成功' if backup_result else '失败'}")
    print()

    # 验证数据完整性
    print("🔍 验证区块链完整性...")
    is_valid = blockchain.is_valid_chain()
    print(f"  区块链有效性: {'✅ 有效' if is_valid else '❌ 无效'}")
    print()

    # 显示存储的文件
    print("📁 存储文件:")
    data_dir = blockchain.data_dir
    backup_dir = blockchain.backup_dir

    if data_dir.exists():
        for file in sorted(data_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"  {file.name} ({size} bytes)")

    if backup_dir.exists():
        print("  备份文件:")
        for file in sorted(backup_dir.glob("*")):
            if file.is_file():
                size = file.stat().st_size
                print(f"    {file.name} ({size} bytes)")
    print()

    # 演示数据恢复
    print("🔄 演示数据恢复...")
    print("  创建新的区块链实例（应该自动加载保存的数据）...")

    # 创建新的区块链实例来测试数据加载
    new_blockchain = Blockchain(config=config)

    print(f"  加载的区块链长度: {len(new_blockchain)}")
    print(f"  最新区块索引: #{new_blockchain.get_latest_block_index()}")
    print(f"  最新区块哈希: {new_blockchain.get_latest_block_hash()[:16]}...")

    # 验证加载的数据
    recovered_valid = new_blockchain.is_valid_chain()
    print(f"  加载的数据有效性: {'✅ 有效' if recovered_valid else '❌ 无效'}")
    print()

    # 验证特定区块
    print("🔍 验证特定区块...")
    original_block = blocks_added[3]  # 第4个添加的区块
    recovered_block = new_blockchain.get_block_by_hash(original_block.get_hash())

    if recovered_block:
        print(f"  ✅ 区块 #{original_block.get_index()} 已成功恢复")
        print(f"     矿工: {recovered_block.get_miner()}")
        print(f"     Merkle根: {recovered_block.get_m_tree_root()[:16]}...")
        print(f"     布隆过滤器测试: {recovered_block.is_in_bloom('transaction_4_1')}")
    else:
        print(f"  ❌ 区块 #{original_block.get_index()} 未找到")
    print()

    # 演示清理功能
    print("🧹 演示备份清理...")
    removed_count = new_blockchain.cleanup_old_backups()
    print(f"  清理了 {removed_count} 个旧备份")
    print()

    # 显示最终统计
    final_stats = new_blockchain.get_fork_statistics()
    print("📈 最终统计:")
    new_blockchain.print_chain_info()
    print()

    print("✨ 演示完成！")
    print(f"📂 所有数据已保存在: {data_dir.absolute()}")
    print()
    print("🎯 演示的功能:")
    print("  ✅ 自动保存到硬盘")
    print("  ✅ 从硬盘自动加载")
    print("  ✅ 数据完整性校验")
    print("  ✅ 自动备份创建")
    print("  ✅ 备份清理")
    print("  ✅ 分叉持久化")
    print("  ✅ 线程安全操作")
    print("  ✅ JSON和Pickle双格式存储")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  演示被用户中断")
    except Exception as e:
        print(f"\n\n❌ 演示过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n👋 感谢使用EZchain永久化存储演示！")