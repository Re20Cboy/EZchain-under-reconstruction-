逐证明单元（proof unit）验证：

核心逻辑：遍历vpb_slice中的Proofs_slice中的proof unit，验证每个阶段的价值持有与转移合法性（无双花）。

场景案例：
假设目标value的真实的所有权转移历史如下（被记录进main_chain_info）：
创世块（区块0）：alice是目标value的首位所有者（从GOD处获得）
区块8：alice作为sender提交交易（非目标value）
区块15：bob从alice处接收目标value（alice->bob交易）
区块16：bob作为sender提交交易（非目标value）
区块25：bob作为sender提交交易（非目标value）
区块27：charlie从bob处接收目标value（bob->charlie交易）
区块55：charlie作为sender提交交易（非目标value）
区块56：dave从charlie处接收目标value（charlie->dave交易）
区块58（当前待验证交易）：eve从dave处接收目标value（dave->eve交易）

根据bloom_filter_validator中提取的信息（主要是bloom_filter_validator.py代码中的owner_epochs = extractor.extract_owner_epochs(vpb_slice.block_index_slice)，以及first_start_block, first_owner = owner_epochs[0]），可知：
- alice在0块获得目标Value（GOD->alice），在[8]中提交了其他交易，在15块将目标value转移给bob（alice->bob）；
- bob在15块获得目标Value（alice->bob）,在[16, 25]中提交了其他交易，在27块将目标value转移给charlie（bob->charlie）；
- charlie在27块获得目标Value（bob->charlie）,在[55]中提交了其他交易，在56块将目标value转移给dave（charlie->dave）；
- dave在56块获得目标Value（charlie->dave）,在58块将目标value转移给eve（dave->eve，即当前待验证的交易）；

proof validator需要对以上目标value的流转历史相关信息进行逐一核验，具体流程包括：
1. 默克尔树检测：针对Proofs_slice中所有的proof units,测试它们是否符合主链信息main_chain_info中的默克尔树根检测，即，从每个proof unit的交易内容信息可以推导出叶子节点hash，然后再从叶子节点可以利用默克尔树证明推导出root信息，和main_chain_info中包含的此块的root信息对比，若不一致则测试不通过。
2. 非目标值交易验证（双花检测）：vpb_slice.block_index_slice.index_lst（在此例中其应为：[0,8,15,16,25,27,55,56,58]）中的[8, 16, 25, 55]对应的proof units（即，Proofs_slice中的第2、4、5、7个proof unit），验证每个proof unit的交易内容中包含的所有value均与目标value无任何交集（否则说明存在目标value的双花，测试不通过）。
3. 目标值交易验证：vpb_slice.block_index_slice.index_lst（在此例中其应为：[0,8,15,16,25,27,55,56,58]）中的[0, 15, 27, 56, 58]对应的proof units（即，Proofs_slice中的第1、3、6、8、9个proof unit），验证每个proof unit的交易内容中包含的value均与目标value完全重合（若是组合支付，即，一笔交易包含多个value的情况，则其有且仅有中一个交易与目标value完全重合），且交易的发送方和接收方必须满足GOD->alice、alice->bob、bob->charlie、charlie->dave、dave->eve的流转“路径”，若以上过程中有任何不符合的情况，则测试不通过。
