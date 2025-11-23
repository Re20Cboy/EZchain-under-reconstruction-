V-P-B 验证案例：

假设：account addr=0X418ab
Value：[begin_index=0X0000, end_index=0X0100]
Proofs: [pu_1, pu_2, pu_3, pu_4, pu_5, pu_6, pu_7]
block_index_lst: (index_lst= [0, 7, 15, 27, 56, 67, 98]; owner=[(0, 0X418ab), (15, 0X8360c), (56, 0X14860)])
注意，这里的Proofs中proof unit（pu）的数量是和index_lst的元素（即，记录的区块号）的是相等的，一一对应的。
那么若account（0X418ab）有一个关于Value的checkpoint记录，区块高度为14，即此account（0X418ab）在14区块高度时持有此value，那么account（0X418ab）在检测此value时也不需要对高度14之前的Proofs和block_index_lst进行检测，即，只需检测以下Proofs+block_index_lst的历史“切片”：
Proofs_切片: [pu_3, pu_4, pu_5, pu_6, pu_7]
block_index_lst_切片: (index_lst_切片= [15, 27, 56, 67, 98]; owner_切片=[(15, 0X8360c), (56, 0X14860)])
观察上述切片信息，其实就是直接删去了Proofs与block_index_lst中区块高度小于等于14的信息。

*：事实上，原始的“Proofs+block_index_lst”也是一种“切片”，只不过它是完全没有被截断的全量切片。

对于“Proofs_切片+block_index_lst_切片”，进行如下的验证：
1）基础的数据结构合法性验证：
核心逻辑：确保输入数据结构符合规范，避免无效验证。
数据类型校验：Proofs_切片任然为Proofs数据结构；block_index_lst_切片仍然为BlockIndexList数据结构；Value的数据结构为Value；Proofs中proof unit（pu）的数量是和index_lst的元素（即，记录的区块号）的是相等的；等等
Value结构校验：Value是合法的值，即，num>0，begin index < end index等等。

2）block_index_lst_切片的布隆过滤器验证：
核心逻辑：验证block_index_lst_切片信息与主链的布隆过滤器声明相吻合。
首先提取owner_切片中的具体地址信息，即：（0X8360c, 0X14860）；
然后检测：从高度15到高度56之间（即，0X8360c持有此value到交易此value所经历的所有区块高度），0X8360c在哪些区块提交过交易（通过主链布隆过滤器检测），得到一个数组 ，如[27, 56]；从高度56到高度98之间（即，0X14860持有此value到最新块高度98之间），0X14860在哪些区块提交过交易（通过主链布隆过滤器检测），得到一个数组 ，如 [67，98]；
再将上述根据主链布隆过滤器得到的数组相加，得到一个标准数组：[15]+[27，56]+[67，98]=[15, 27, 56, 67, 98]（注意，这里“[15]+”是为了补全最开始的区块高度，然后所有的“+”法均是忽略重复项的，例如，[15]+[15, 27，56]=[15, 27，56]）
最后用标准数组与index_lst_切片对比，若一致则该项测试通过，反之不通过。

3）逐证明单元（proof unit）验证：
核心逻辑：遍历Proofs_切片中的proof unit，验证每个阶段的价值持有与转移合法性（无双花）。
可以记每个（不同的）owner持有此value所经历的区块高度为一个epoch，例如，对于0X8360c而言，其对应的epoch(0X8360c)=[15, 27, 56]（因0X8360c在高度15获得此value，在高度56支付此value）。
那么在此epoch(0X8360c)内，可根据主链的默克尔树根来判断Proofs_切片中此epoch对应proof unit的正确性，即，[pu_3, pu_4, pu_5]的正确性（包括默克尔树根检测，pu的树根是否匹配对应主链上记录的树根，叶子节点是否符合默克尔树证明。叶子节点的数据结构是否符合MultiTransactions等等）。
然后还需要检测在此epoch(0X8360c)内，此value没有双花，即，[pu_3, pu_4, pu_5]所包含的所有交易中，value有且只能有一次被花销，必须是在高度56中，0X8360c向0X14860支付了此value（value所有权也转移到了0X14860手上）。
遵循以上的验证逻辑，对所有epoch进行验证，若全部通过，该项测试通过，反之不通过。

4）需注意事项：
- 由于创世块是直接向相关地址派发value，因此其检测需要单独进行处理。
- 这里的验证代码在实现中需要考虑具体的性能与内存需求（例如，在读取主链时，可以“分段”处理，而不是把一长串主链直接读入内存挨个验证，这样太耗费内存空间）。
