切片生成：

核心逻辑：若有检查点，则根据检查点信息，将VPB进行相应的截断后输出；若无检查点，则无需截断，将VPB整理为标准格式后输出。

场景案例1（有checkpoint）：
假设目标value的真实的所有权转移历史如下（相关信息被记录进main_chain_info的布隆过滤器和默克尔树根）：
创世块（区块0）：alice是目标value的首位所有者（从GOD处获得）
区块8：alice作为sender提交交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob作为sender提交交易（非目标value）
区块25：bob作为sender提交交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie作为sender提交交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58（当前待验证交易）：bob从dave处接收目标value（dave->bob交易）

由于bob曾拥有过目标value，因此bob在面对dave->bob交易时，bob本地是有可触发的checkpoint的（即，bob最后在区块26处拥有目标value），bob根据其checkpoint截断后的proofs_slice和block_index_slice应当是：
block_index_slice.index_lst为[27,55,56,58]（27区块（=checkpoint中记录的区块号+1）之前的序号“裁剪”掉）；
block_index_slice.owner以及block_index_slice中的其他信息则按照相应的规则进行裁剪（27区块之前的序号相对应的数据“裁剪”掉）。
proofs_slice也是同理，因为proofs_slice和block_index_slice是一一对应的（否则无法通过第一步的数据结构检查），因此，block_index_slice.index_lst中的开头的裁剪长度就是proofs_slice的开头的裁剪长度，在proofs_slice中从头裁剪掉相同数量的元素即可。
---------------------------
场景案例2（无checkpoint）：
假设目标value的真实的所有权转移历史如下（相关信息被记录进main_chain_info的布隆过滤器和默克尔树根）：
创世块（区块0）：alice是目标value的首位所有者（从GOD处获得）
区块8：alice作为sender提交交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob作为sender提交交易（非目标value）
区块25：bob作为sender提交交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie作为sender提交交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58（当前待验证交易）：eve从dave处接收目标value（dave->eve交易）

由于eve未曾拥有过目标value，因此不会触发checkpoint，因此无需对原始的vpb截断，直接根据原始的vpb输出未截断的vpb_slice即可：
即，block_index_slice.index_lst为[0,8,15,16,25,27,55,56,58]（原始vpb无任何截断），其他数据同理。
