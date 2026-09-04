from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """MVP 内存存储；生产环境替换为 PostgreSQL/Redis 实现。"""

    def __init__(self) -> None:
        # RLock 允许一个业务事务在持锁期间写入审计事件，避免并发审批时死锁。
        self.lock = RLock()
        self.products = [
            {"id": "p1001", "name": "轻量通勤双肩包", "price": 199.0, "list_price": 239.0, "stock": 88, "category": "箱包", "brand": "城市行者", "badge": "通勤热卖", "description": "防泼水电脑包，适合 15.6 英寸笔记本。", "image_url": "/assets/p1001.jpg", "rating": 4.8, "review_count": 1240, "sales": 1200, "tags": ["防泼水", "电脑隔层"], "specs": {"材质": "高密度涤纶", "容量": "20L", "适配": "15.6 英寸"}},
            {"id": "p1002", "name": "降噪蓝牙耳机", "price": 329.0, "list_price": 399.0, "stock": 42, "category": "手机数码", "brand": "声域", "badge": "数码热榜", "description": "支持主动降噪、双设备连接和 30 小时续航。", "image_url": "/assets/p1002.jpg", "rating": 4.9, "review_count": 3480, "sales": 3480, "tags": ["主动降噪", "30h 续航"], "specs": {"降噪": "-42dB", "续航": "30 小时", "连接": "蓝牙 5.3"}, "variants": {"颜色": ["曜石黑", "云雾白"], "版本": ["标准版", "降噪增强版"]}},
            {"id": "p1003", "name": "有机棉家居四件套", "price": 269.0, "list_price": 329.0, "stock": 25, "category": "家居", "brand": "棉序", "badge": "品质家居", "description": "纯棉亲肤面料，支持 7 天无理由退货。", "image_url": "/assets/p1003.jpg", "rating": 4.7, "review_count": 860, "sales": 860, "tags": ["纯棉亲肤", "可机洗"], "specs": {"面料": "100% 有机棉", "规格": "1.5m / 1.8m", "件数": "四件套"}},
            {"id": "p1004", "name": "城市轻跑运动鞋", "price": 399.0, "list_price": 459.0, "stock": 31, "category": "服饰", "brand": "跃行", "badge": "跑步精选", "description": "轻弹缓震鞋底，适合通勤与日常慢跑。", "image_url": "/assets/p1004.jpg", "rating": 4.8, "review_count": 2100, "sales": 2100, "tags": ["轻量缓震", "透气网面"], "specs": {"鞋面": "透气网布", "鞋底": "EVA 缓震", "尺码": "35-45"}},
            {"id": "p1005", "name": "精品手冲咖啡豆 500g", "price": 159.0, "list_price": 199.0, "stock": 64, "category": "食品", "brand": "山野咖啡", "badge": "咖啡精选", "description": "精选阿拉比卡咖啡豆，中浅度烘焙，适合手冲、法压壶与美式咖啡。", "image_url": "/assets/p1005.jpg", "rating": 4.6, "review_count": 740, "sales": 740, "tags": ["阿拉比卡豆", "中浅烘焙"], "specs": {"产地": "云南/哥伦比亚", "烘焙度": "中浅烘焙", "净含量": "500g"}},
            {"id": "p1006", "name": "桌面智能台灯", "price": 239.0, "list_price": 299.0, "stock": 18, "category": "家居", "brand": "光屿", "badge": "护眼好物", "description": "无频闪护眼光源，支持定时和三档色温。", "image_url": "/assets/p1006.jpg", "rating": 4.8, "review_count": 530, "sales": 530, "tags": ["无频闪", "三档色温"], "specs": {"色温": "2700-5000K", "显色": "Ra95", "控制": "触控/定时"}},
            {"id": "p1007", "name": "轻奢智能手表", "price": 599.0, "list_price": 699.0, "stock": 17, "category": "手机数码", "brand": "时刻", "badge": "新品", "description": "全天候健康记录，支持运动模式和消息提醒。", "image_url": "/assets/p1007.jpg", "rating": 4.8, "review_count": 1680, "sales": 1680, "tags": ["健康监测", "运动记录"], "specs": {"屏幕": "1.78 英寸 AMOLED", "续航": "12 天", "防水": "5ATM"}, "variants": {"表壳": ["星云银", "曜石黑"], "表带": ["运动硅胶", "真皮表带"]}},
            {"id": "p1008", "name": "偏光太阳镜", "price": 189.0, "list_price": 229.0, "stock": 46, "category": "服饰", "brand": "晴野", "badge": "旅行必备", "description": "轻盈镜架搭配偏光镜片，通勤和旅行都适合。", "image_url": "/assets/p1008.jpg", "rating": 4.7, "review_count": 920, "sales": 920, "tags": ["偏光镜片", "轻盈镜架"], "specs": {"镜片": "UV400 偏光", "镜架": "TR90", "适用": "通用脸型"}},
            {"id": "p1009", "name": "黑色菱格链条斜挎包", "price": 259.0, "list_price": 299.0, "stock": 29, "category": "箱包", "brand": "日常集", "badge": "轻奢通勤", "description": "黑色菱格纹包身搭配金属链条肩带，小巧结构适合通勤与约会。", "image_url": "/assets/p1009.jpg", "rating": 4.6, "review_count": 680, "sales": 680, "tags": ["菱格纹", "链条肩带"], "specs": {"材质": "PU 皮革/金属链", "容量": "手机与随身小物", "背法": "单肩/斜挎"}},
            {"id": "p1010", "name": "氨基酸洁面泡沫", "price": 89.0, "list_price": 109.0, "stock": 120, "category": "个护", "brand": "净研", "badge": "回购榜", "description": "温和清洁配方，洗后清爽不紧绷。", "image_url": "/assets/p1010.jpg", "rating": 4.8, "review_count": 5200, "sales": 5200, "tags": ["温和清洁", "敏感肌友好"], "specs": {"容量": "150ml", "配方": "氨基酸表活", "适用": "所有肤质"}},
            {"id": "p1011", "name": "桌面多肉绿植盆栽", "price": 79.0, "list_price": 99.0, "stock": 35, "category": "家居", "brand": "森日", "badge": "桌面美学", "description": "清新耐养的单株多肉绿植，搭配简约陶瓷花盆，适合书桌与窗台。", "image_url": "/assets/p1011.jpg", "rating": 4.5, "review_count": 410, "sales": 410, "tags": ["耐养绿植", "陶瓷花盆"], "specs": {"植物": "多肉绿植", "花盆": "陶瓷", "数量": "1 盆", "养护": "散射光"}},
            {"id": "p1012", "name": "无线办公键盘", "price": 299.0, "list_price": 359.0, "stock": 22, "category": "电脑办公", "brand": "桌面集", "badge": "办公优选", "description": "低噪剪刀脚结构与全尺寸布局，支持蓝牙多设备切换，适合办公与居家学习。", "image_url": "/assets/p1012.jpg", "rating": 4.9, "review_count": 2150, "sales": 2150, "tags": ["低噪输入", "多设备切换"], "specs": {"结构": "剪刀脚薄膜", "配列": "全尺寸", "连接": "蓝牙/USB-C"}, "variants": {"配色": ["银白", "深空灰"]}},
            # 扩充商品中心：覆盖家电、运动、美妆、母婴和办公等典型电商类目。
            {"id": "p1013", "name": "现代简约整体橱柜定制订金", "price": 459.0, "list_price": 529.0, "stock": 26, "category": "家居", "brand": "栖居", "badge": "空间定制", "description": "白色极简整体厨房设计方案，包含上门量房、布局规划与橱柜材质选配服务。", "image_url": "/assets/p1013.jpg", "rating": 4.8, "review_count": 318, "sales": 980, "tags": ["上门量房", "整体橱柜"], "specs": {"商品类型": "定制服务订金", "布局": "一字型/L 型可选", "柜门": "环保饰面板", "服务": "量房与方案设计"}},
            {"id": "p1014", "name": "轻户外防晒外套", "price": 219.0, "list_price": 269.0, "stock": 58, "category": "服饰", "brand": "寻野", "badge": "新品", "description": "UPF50+ 防晒面料，轻薄透气，适合通勤与露营。", "image_url": "/assets/p1014.jpg", "rating": 4.7, "review_count": 426, "sales": 1230, "tags": ["UPF50+", "轻薄透气"], "specs": {"面料": "锦纶防晒布", "版型": "宽松", "颜色": "湖蓝/米白"}},
            {"id": "p1015", "name": "轻奢日常彩妆组合套装", "price": 129.0, "list_price": 159.0, "stock": 96, "category": "美妆", "brand": "澄肌", "badge": "彩妆热卖", "description": "眼影、腮红、口红与睫毛膏组合，覆盖通勤妆和约会妆的常用色系。", "image_url": "/assets/p1015.jpg", "rating": 4.8, "review_count": 1180, "sales": 3150, "tags": ["日常配色", "一套成妆"], "specs": {"套装": "眼影/腮红/唇膏/睫毛膏", "妆效": "自然通勤", "保质期": "3 年"}},
            {"id": "p1016", "name": "人体工学办公椅", "price": 899.0, "list_price": 1099.0, "stock": 14, "category": "家居", "brand": "序坐", "badge": "品质选", "description": "可调腰托与 3D 扶手，支持长时间办公坐姿。", "image_url": "/assets/p1016.jpg", "rating": 4.6, "review_count": 154, "sales": 360, "tags": ["可调腰托", "久坐友好"], "specs": {"承重": "120kg", "扶手": "3D 可调", "椅背": "透气网布"}},
            {"id": "p1017", "name": "加厚防滑瑜伽垫 6mm", "price": 69.0, "list_price": 99.0, "stock": 120, "category": "运动", "brand": "元动", "badge": "健身热卖", "description": "高密度防滑瑜伽垫，可卷收纳，适合居家瑜伽、拉伸和基础力量训练。", "image_url": "/assets/p1017.jpg", "rating": 4.7, "review_count": 652, "sales": 1870, "tags": ["6mm 加厚", "双面防滑"], "specs": {"厚度": "6mm", "材质": "高密度 TPE", "尺寸": "183×61cm", "收纳": "可卷收纳"}},
            {"id": "p1018", "name": "婴幼儿遮阳游泳圈套装", "price": 99.0, "list_price": 129.0, "stock": 75, "category": "母婴", "brand": "泡泡湾", "badge": "亲子戏水", "description": "带遮阳顶篷的婴幼儿坐式游泳圈，适合家长陪同下的浅水戏水场景。", "image_url": "/assets/p1018.jpg", "rating": 4.9, "review_count": 540, "sales": 920, "tags": ["遮阳顶篷", "坐式支撑"], "specs": {"类型": "婴幼儿坐式游泳圈", "材质": "环保 PVC", "适用": "家长全程陪同", "提示": "非救生用品"}},
            {"id": "p1019", "name": "意式手工披萨双拼套餐", "price": 139.0, "list_price": 179.0, "stock": 44, "category": "食品", "brand": "食刻", "badge": "现烤推荐", "description": "手工饼底搭配丰富芝士与双拼馅料，加热即食，适合家庭聚餐和周末分享。", "image_url": "/assets/p1019.jpg", "rating": 4.6, "review_count": 377, "sales": 1120, "tags": ["手工饼底", "芝士双拼"], "specs": {"规格": "10 英寸×2", "口味": "经典双拼", "保存": "冷冻保存", "食用": "烤箱/空气炸锅加热"}},
            {"id": "p1020", "name": "低脂蔬果轻食沙拉套餐", "price": 59.0, "list_price": 69.0, "stock": 180, "category": "食品", "brand": "鲜食刻", "badge": "轻食榜", "description": "蔬菜、牛油果和谷物搭配的即食轻食套餐，冷链配送，开盒即食。", "image_url": "/assets/p1020.jpg", "rating": 4.7, "review_count": 912, "sales": 2680, "tags": ["新鲜蔬果", "冷链配送"], "specs": {"规格": "单人份×3", "搭配": "蔬菜/水果/谷物", "保存": "0-4℃ 冷藏", "保质期": "3 天"}},
            {"id": "p1021", "name": "商务镂空自动机械腕表", "price": 1299.0, "list_price": 1599.0, "stock": 37, "category": "服饰", "brand": "时序", "badge": "机械美学", "description": "经典圆形表盘搭配镂空机芯视窗与棕色真皮表带，适合商务和正式场合。", "image_url": "/assets/digital-smartwatch-v2.jpg", "rating": 4.6, "review_count": 203, "sales": 580, "tags": ["自动机械", "真皮表带"], "specs": {"机芯": "自动机械机芯", "表径": "42mm", "表带": "牛皮", "防水": "日常生活防水"}},
            {"id": "p1022", "name": "桌面显示器键鼠套装", "price": 189.0, "list_price": 229.0, "stock": 49, "category": "电脑办公", "brand": "桌面集", "badge": "桌面热榜", "description": "包含桌面显示器、键盘与无线鼠标的入门套装，适合学习、办公和轻度娱乐。", "image_url": "/assets/p1022.jpg", "rating": 4.8, "review_count": 688, "sales": 1410, "tags": ["桌面套装", "即插即用"], "specs": {"显示器": "桌面显示器", "键盘": "有线键盘", "鼠标": "无线鼠标"}},
            {"id": "p1023", "name": "都市街景艺术摄影装饰画", "price": 279.0, "list_price": 329.0, "stock": 105, "category": "家居", "brand": "映城", "badge": "空间美学", "description": "以雨后都市街景倒影为主题的摄影装饰画，适合客厅、书房和工作室。", "image_url": "/assets/p1023.jpg", "rating": 4.8, "review_count": 1106, "sales": 2260, "tags": ["城市摄影", "装饰画"], "specs": {"画面": "都市街景摄影", "尺寸": "50×70cm", "装裱": "黑色铝合金框", "安装": "附无痕挂件"}},
            # 数码频道使用本地化真实摄影资源，覆盖手机、平板、影像、电脑、游戏和智能设备。
            {"id": "p1024", "name": "旗舰影像智能手机 256GB", "price": 4299.0, "list_price": 4799.0, "stock": 36, "category": "手机数码", "brand": "凌光", "badge": "旗舰新品", "description": "高刷 OLED 屏幕与旗舰影像系统，支持双卡 5G 和无线充电。", "image_url": "/assets/real-phone.jpg", "rating": 4.9, "review_count": 2860, "sales": 4630, "tags": ["旗舰影像", "120Hz 高刷"], "specs": {"存储": "256GB", "屏幕": "6.7 英寸 OLED", "网络": "双卡 5G", "保修": "1 年"}},
            {"id": "p1025", "name": "轻薄学习平板 11 英寸", "price": 2699.0, "list_price": 2999.0, "stock": 28, "category": "手机数码", "brand": "云笺", "badge": "学习精选", "description": "2.5K 护眼屏与四扬声器，适合笔记、影音和轻办公。", "image_url": "/assets/real-tablet.jpg", "rating": 4.8, "review_count": 1250, "sales": 1920, "tags": ["2.5K 护眼屏", "手写笔支持"], "specs": {"屏幕": "11 英寸 2.5K", "存储": "128GB", "电池": "8600mAh", "重量": "485g"}},
            {"id": "p1026", "name": "全画幅微单相机套装", "price": 8999.0, "list_price": 9699.0, "stock": 12, "category": "摄影摄像", "brand": "镜界", "badge": "影像旗舰", "description": "全画幅传感器与高速眼部对焦，含标准变焦镜头。", "image_url": "/assets/real-camera.jpg", "rating": 4.9, "review_count": 486, "sales": 720, "tags": ["全画幅", "4K 视频"], "specs": {"传感器": "全画幅 CMOS", "像素": "3300 万", "视频": "4K 60P", "镜头": "28-70mm"}},
            {"id": "p1027", "name": "银色轻薄笔记本电脑 14 英寸", "price": 6299.0, "list_price": 6899.0, "stock": 21, "category": "电脑办公", "brand": "云际", "badge": "办公旗舰", "description": "银色金属机身与大尺寸触控板，适合开发、差旅和移动办公。", "image_url": "/assets/real-laptop.jpg", "rating": 4.8, "review_count": 930, "sales": 1480, "tags": ["金属机身", "长续航"], "specs": {"处理器": "高性能 12 核", "内存": "32GB", "硬盘": "1TB SSD", "屏幕": "14 英寸 2.8K", "重量": "1.32kg"}},
            {"id": "p1028", "name": "次世代家庭游戏主机", "price": 3599.0, "list_price": 3899.0, "stock": 16, "category": "游戏娱乐", "brand": "极境", "badge": "游戏热榜", "description": "支持 4K 高帧游戏与光线追踪，含无线手柄。", "image_url": "/assets/real-console.jpg", "rating": 4.9, "review_count": 1760, "sales": 2530, "tags": ["4K 游戏", "光线追踪"], "specs": {"存储": "1TB SSD", "输出": "4K 120Hz", "手柄": "无线震动", "保修": "1 年"}},
            {"id": "p1029", "name": "桌面无线高保真音箱", "price": 899.0, "list_price": 1099.0, "stock": 32, "category": "游戏娱乐", "brand": "声场", "badge": "音质精选", "description": "双单元立体声与多设备无线连接，适合桌面影音。", "image_url": "/assets/real-speaker.jpg", "rating": 4.7, "review_count": 680, "sales": 990, "tags": ["高保真", "无线连接"], "specs": {"功率": "60W", "连接": "蓝牙/光纤/AUX", "声道": "2.0", "材质": "木质箱体"}},
            {"id": "p1030", "name": "Apple iMac 一体机 27 英寸", "price": 2199.0, "list_price": 2499.0, "stock": 24, "category": "电脑办公", "brand": "Apple", "badge": "设计师选", "description": "一体化桌面机身，配备高分辨率显示屏、键盘和触控板，适合设计与内容创作。", "image_url": "/assets/real-monitor.jpg", "rating": 4.8, "review_count": 510, "sales": 810, "tags": ["一体机", "高分辨率屏"], "specs": {"形态": "一体式桌面电脑", "屏幕": "27 英寸 Retina", "内存": "16GB", "配件": "键盘 + 触控板"}},
            {"id": "p1031", "name": "便携航拍无人机套装", "price": 4999.0, "list_price": 5499.0, "stock": 9, "category": "摄影摄像", "brand": "逐风", "badge": "航拍新品", "description": "三轴云台、智能跟随与长续航，含双电池收纳套装。", "image_url": "/assets/real-drone.jpg", "rating": 4.8, "review_count": 352, "sales": 530, "tags": ["三轴云台", "智能跟随"], "specs": {"视频": "4K HDR", "续航": "34 分钟", "图传": "10km", "套装": "双电池"}},
            {"id": "p1032", "name": "直屏旗舰影像手机 512GB", "price": 6999.0, "list_price": 7499.0, "stock": 14, "category": "手机数码", "brand": "凌光", "badge": "影像旗舰", "description": "简洁直屏机身、专业长焦影像与大容量存储，适合商务办公和移动创作。", "image_url": "/assets/digital-phone-fold.jpg", "rating": 4.8, "review_count": 742, "sales": 1160, "tags": ["直屏旗舰", "512GB", "长焦影像"], "specs": {"屏幕": "6.7 英寸 OLED", "刷新率": "120Hz", "存储": "512GB", "保修": "1 年"}, "variants": {"颜色": ["曜石黑", "冰川蓝"], "存储": ["256GB", "512GB"]}},
            {"id": "p1033", "name": "专业影像手机 Pro", "price": 5199.0, "list_price": 5699.0, "stock": 20, "category": "手机数码", "brand": "镜界", "badge": "影像专享", "description": "大底主摄与自然色彩屏幕，支持 RAW 拍摄和 8K 视频。", "image_url": "/assets/digital-phone-camera.jpg", "rating": 4.9, "review_count": 968, "sales": 1840, "tags": ["大底主摄", "8K 视频"], "specs": {"主摄": "1 英寸大底", "视频": "8K 30P", "屏幕": "6.7 英寸 LTPO", "存储": "512GB"}, "variants": {"颜色": ["钛灰", "曜金"], "存储": ["256GB", "512GB"]}},
            {"id": "p1034", "name": "轻薄长续航智能手机", "price": 2399.0, "list_price": 2699.0, "stock": 48, "category": "手机数码", "brand": "云笺", "badge": "学生优选", "description": "轻薄机身配大容量电池，日常学习、影音和游戏都流畅。", "image_url": "/assets/digital-phone-slim.jpg", "rating": 4.7, "review_count": 1320, "sales": 2570, "tags": ["轻薄机身", "6000mAh"], "specs": {"屏幕": "6.6 英寸 120Hz", "电池": "6000mAh", "快充": "67W", "重量": "188g"}, "variants": {"颜色": ["极光紫", "深海蓝", "云雾白"], "存储": ["128GB", "256GB"]}},
            {"id": "p1035", "name": "高性能创作笔记本 14 英寸", "price": 7599.0, "list_price": 8299.0, "stock": 18, "category": "电脑办公", "brand": "云际", "badge": "创作者本", "description": "窄边框高色域屏幕与高性能处理器，适合视频剪辑、开发和设计工作。", "image_url": "/assets/digital-laptop-creator.jpg", "rating": 4.9, "review_count": 614, "sales": 920, "tags": ["高色域屏", "32GB 内存"], "specs": {"处理器": "12 核高性能处理器", "内存": "32GB", "硬盘": "1TB SSD", "屏幕": "14 英寸高色域"}, "variants": {"内存": ["16GB", "32GB"], "硬盘": ["512GB", "1TB"]}},
            {"id": "p1036", "name": "专业四通道 DJ 调音台", "price": 4699.0, "list_price": 5199.0, "stock": 26, "category": "游戏娱乐", "brand": "声场", "badge": "专业影音", "description": "四通道专业混音控制台，配备独立均衡、效果控制与监听接口，适合演出和音乐创作。", "image_url": "/assets/digital-speaker-v5.jpg", "rating": 4.7, "review_count": 386, "sales": 760, "tags": ["四通道混音", "专业控制"], "specs": {"通道": "4 通道", "输入": "线路/麦克风", "监听": "独立耳机监听", "用途": "现场演出/音乐制作"}, "variants": {"版本": ["标准版", "演出版"]}},
            {"id": "p1037", "name": "旗舰头戴降噪耳机", "price": 1299.0, "list_price": 1499.0, "stock": 33, "category": "手机数码", "brand": "声域", "badge": "通勤首选", "description": "自适应主动降噪、空间音频和舒适头梁，长时间佩戴不压耳。", "image_url": "/assets/digital-headphones-v2.jpg", "rating": 4.8, "review_count": 816, "sales": 1430, "tags": ["自适应降噪", "空间音频"], "specs": {"降噪": "-48dB", "续航": "40 小时", "连接": "蓝牙 5.4", "重量": "258g"}, "variants": {"颜色": ["午夜黑", "象牙白"]}},
            {"id": "p1038", "name": "真无线降噪耳机 2", "price": 499.0, "list_price": 599.0, "stock": 67, "category": "手机数码", "brand": "声域", "badge": "爆款升级", "description": "小巧入耳设计，支持通透模式、双麦通话和无线充电。", "image_url": "/assets/digital-earbuds.jpg", "rating": 4.7, "review_count": 1920, "sales": 3860, "tags": ["通透模式", "无线充电"], "specs": {"续航": "单次 8 小时", "防水": "IPX4", "连接": "蓝牙 5.3", "充电": "无线充电盒"}, "variants": {"颜色": ["云雾白", "曜石黑"]}},
            {"id": "p1039", "name": "运动健康智能手表 Pro", "price": 899.0, "list_price": 999.0, "stock": 29, "category": "手机数码", "brand": "时刻", "badge": "运动新品", "description": "全天候心率、血氧和睡眠监测，支持 GPS 户外运动轨迹。", "image_url": "/assets/digital-smartwatch-v3.jpg", "rating": 4.8, "review_count": 536, "sales": 780, "tags": ["GPS 定位", "睡眠监测"], "specs": {"屏幕": "1.9 英寸 AMOLED", "续航": "14 天", "防水": "5ATM", "定位": "双频 GPS"}, "variants": {"表壳": ["银色", "黑色"], "表带": ["硅胶", "氟橡胶"]}},
            {"id": "p1040", "name": "低延迟电竞机械键盘", "price": 459.0, "list_price": 529.0, "stock": 37, "category": "电脑办公", "brand": "键界", "badge": "电竞装备", "description": "全键热插拔、RGB 灯效与 2.4G 低延迟连接，兼顾办公和游戏。", "image_url": "/assets/digital-keyboard-v2.jpg", "rating": 4.8, "review_count": 448, "sales": 1080, "tags": ["热插拔", "低延迟"], "specs": {"配列": "98 键", "轴体": "线性快银轴", "连接": "2.4G/蓝牙/有线", "续航": "120 小时"}, "variants": {"轴体": ["快银轴", "静音红轴"], "配色": ["雾灰", "深空黑"]}},
            {"id": "p1041", "name": "轻量化低延迟无线鼠标", "price": 259.0, "list_price": 299.0, "stock": 54, "category": "电脑办公", "brand": "键界", "badge": "办公优选", "description": "人体工学鼠标机身与低延迟无线连接，适合办公、设计和日常游戏。", "image_url": "/assets/digital-mouse-v2.jpg", "rating": 4.7, "review_count": 732, "sales": 1750, "tags": ["人体工学", "低延迟无线"], "specs": {"连接": "蓝牙/2.4G", "续航": "18 个月", "DPI": "800-4000", "重量": "92g"}, "variants": {"颜色": ["云雾白", "石墨黑"]}},
            {"id": "p1042", "name": "桌面 Hi-Fi 蓝牙音箱 2.0", "price": 399.0, "list_price": 459.0, "stock": 41, "category": "游戏娱乐", "brand": "声场", "badge": "桌面影音", "description": "左右双箱体立体声设计，适合电脑桌面、游戏娱乐与家庭影音使用。", "image_url": "/assets/digital-speaker-v4.jpg", "rating": 4.7, "review_count": 642, "sales": 1290, "tags": ["2.0 立体声", "桌面音箱"], "specs": {"形态": "左右双音箱", "功率": "40W", "连接": "蓝牙/AUX", "用途": "电脑/电视/游戏主机"}, "variants": {"颜色": ["曜石黑"]}},
            {"id": "p1043", "name": "高性能光驱版家庭游戏主机", "price": 3599.0, "list_price": 3899.0, "stock": 23, "category": "游戏娱乐", "brand": "极境", "badge": "主机热榜", "description": "高性能家用游戏主机，支持 4K HDR、光线追踪与高速固态存储，含无线手柄。", "image_url": "/assets/digital-console-v2.jpg", "rating": 4.6, "review_count": 318, "sales": 670, "tags": ["4K HDR", "光线追踪"], "specs": {"版本": "光驱版", "存储": "1TB SSD", "输出": "4K HDR", "配件": "无线手柄"}, "variants": {"版本": ["光驱版", "数字版"]}},
        ]
        self.shops = [
            {"id": "shop-digital", "name": "数码官方自营馆", "type": "平台自营", "rating": 4.9, "service_score": 4.9, "logistics_score": 4.8, "status": "营业中"},
            {"id": "shop-life", "name": "悦生活品质家居", "type": "品牌旗舰店", "rating": 4.8, "service_score": 4.8, "logistics_score": 4.7, "status": "营业中"},
            {"id": "shop-market", "name": "甄选综合超市", "type": "平台自营", "rating": 4.8, "service_score": 4.9, "logistics_score": 4.9, "status": "营业中"},
        ]
        digital_categories = {"手机数码", "电脑办公", "摄影摄像", "游戏娱乐"}
        life_categories = {"家居", "家电", "运动", "服饰", "箱包"}
        for product in self.products:
            product.setdefault("status", "在售")
            product.setdefault("sku_code", "SKU-" + product["id"].upper())
            product.setdefault("shop_id", "shop-digital" if product["category"] in digital_categories else "shop-life" if product["category"] in life_categories else "shop-market")
        self.carts: dict[str, list[dict]] = {"buyer-demo": []}
        self.orders = [
            {"id": "o20260901001", "buyer_id": "buyer-demo", "status": "待收货", "total": 199.0, "items": [{"product_id": "p1001", "name": "轻量通勤双肩包", "qty": 1}], "logistics": "运输中，预计明日送达", "created_at": now()},
            {"id": "o20260828002", "buyer_id": "buyer-demo", "status": "已完成", "total": 329.0, "items": [{"product_id": "p1002", "name": "降噪蓝牙耳机", "qty": 1}], "logistics": "已签收", "created_at": now()},
        ]
        # 预置两条匿名演示售后，客服与运营工作台首次打开即可看到可处理队列。
        self.after_sales: dict[str, dict] = {
            "as-demo-1001": {
                "id": "as-demo-1001", "buyer_id": "buyer-demo", "order_id": "o20260828002",
                "amount": 329.0, "reason": "耳机左耳无声，希望退货退款", "evidence_confidence": 0.91,
                "status": "SUSPENDED_HUMAN", "outcome": "PENDING", "decision": "AMOUNT_REVIEW_REQUIRED", "risk_score": 28,
                "references": [{"id": "kb-refund-001", "title": "平台售后政策 v3", "version": "3.0"}],
                "trace_id": "trace-demo-as-1001", "assigned_to": "csr-002", "state_history": [{"state": "RUNNING", "at": now(), "reason": "case_created"}, {"state": "SUSPENDED_HUMAN", "at": now(), "reason": "AMOUNT_REVIEW_REQUIRED"}], "created_at": now(),
            },
            "as-demo-1002": {
                "id": "as-demo-1002", "buyer_id": "buyer-demo", "order_id": "o20260901001",
                "amount": 199.0, "reason": "包装轻微破损，申请部分退款", "evidence_confidence": 0.97,
                "status": "COMPLETED", "outcome": "APPROVED", "decision": "AUTO_REFUND", "risk_score": 18,
                "references": [{"id": "kb-refund-001", "title": "平台售后政策 v3", "version": "3.0"}],
                "trace_id": "trace-demo-as-1002", "state_history": [{"state": "RUNNING", "at": now(), "reason": "case_created"}, {"state": "COMPLETED", "at": now(), "reason": "AUTO_REFUND"}], "created_at": now(),
            },
        }
        self.payments: dict[str, dict] = {}
        self.tickets: dict[str, dict] = {
            "tk-demo-1001": {
                "id": "tk-demo-1001", "buyer_id": "buyer-demo", "subject": "物流停滞需要催件",
                "message": "订单已经三天没有更新，麻烦帮忙查询。", "order_id": "o20260901001", "priority": "high",
                "status": "open", "assignee": None, "created_at": now(),
                "messages": [{"sender": "buyer", "message": "订单已经三天没有更新，麻烦帮忙查询。", "created_at": now()}],
            },
            "tk-demo-1002": {
                "id": "tk-demo-1002", "buyer_id": "buyer-demo", "subject": "耳机连接问题",
                "message": "蓝牙耳机偶尔断连，想确认售后处理方式。", "order_id": "o20260828002", "priority": "normal",
                "status": "in_progress", "assignee": "agent-demo", "created_at": now(),
                "messages": [
                    {"sender": "buyer", "message": "蓝牙耳机偶尔断连，想确认售后处理方式。", "created_at": now()},
                    {"sender": "客服", "message": "已接单，正在核对商品说明与售后政策。", "created_at": now()},
                ],
            },
        }
        self.favorites: dict[str, set[str]] = {"buyer-demo": {"p1002", "p1007"}}
        self.addresses: dict[str, list[dict]] = {"buyer-demo": [{"id": "addr-001", "label": "家", "receiver": "张先生", "phone": "138****5678", "address": "北京市朝阳区示例路 1 号", "is_default": True}]}
        self.coupons: dict[str, list[dict]] = {"buyer-demo": [
            {"id": "cp-1001", "template_id": "ct-new", "title": "新人满 199 减 20", "amount": 20, "threshold": 199, "scope": "all", "status": "可使用", "expires_at": "2026-10-31"},
            {"id": "cp-1002", "template_id": "ct-digital", "title": "数码满 399 减 50", "amount": 50, "threshold": 399, "scope": "手机数码", "status": "可使用", "expires_at": "2026-09-30"},
            {"id": "cp-1003", "title": "会员专享运费券", "amount": 12, "threshold": 0, "status": "已使用", "expires_at": "2026-08-31"},
        ]}
        self.coupon_templates = [
            {"id": "ct-home", "title": "家居焕新满 299 减 30", "amount": 30, "threshold": 299, "scope": "家居", "remaining": 480, "per_buyer_limit": 1, "expires_at": "2026-12-31", "status": "发放中"},
            {"id": "ct-market", "title": "超市满 99 减 10", "amount": 10, "threshold": 99, "scope": "all", "remaining": 1200, "per_buyer_limit": 1, "expires_at": "2026-12-31", "status": "发放中"},
        ]
        self.inventory_reservations: dict[str, list[dict]] = {}
        self.inventory_ledger: list[dict] = []
        self.invoices: dict[str, dict] = {}
        self.reviews: list[dict] = [
            {"id": "rv-demo-1", "product_id": "p1002", "order_id": "o20260828002", "buyer_id": "buyer-demo", "rating": 5, "content": "降噪效果明显，通勤佩戴很舒服。", "images": [], "created_at": now(), "reply": "感谢认可，我们会持续优化产品体验。"},
        ]
        self.browsing_history: dict[str, list[dict]] = {"buyer-demo": []}
        self.return_shipments: dict[str, dict] = {}
        self.audit_logs: list[dict] = []
        self.refunds: dict[str, dict] = {}
        self.shipments: dict[str, dict] = {}
        self.events: list[dict] = []
        self.rag_gaps: list[dict] = []
        self.intent_records: list[dict] = []
        self.dead_letters: list[dict] = []
        self.voice_sessions: dict[str, dict] = {}
        self.eval_runs: list[dict] = []
        self.idempotency: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}
        self.agent_workloads: dict[str, int] = {
            "csr-001": 2,
            "csr-002": 1,
            "csr-003": 0,
        }
        self.knowledge = [
            {"id": "kb-refund-001", "title": "平台售后政策 v3", "type": "售后政策", "version": "3.0", "status": "published", "text": "商品签收后 7 天内，商品完好且配件齐全支持无理由退货；质量问题可申请退货退款。超过 300 元或存在高风险特征时进入人工审批。", "shop_id": "all", "acl": ["buyer", "agent", "manager", "admin"], "keywords": ["退货退款", "7天无理由", "300元", "人工审批"]},
            {"id": "kb-logistics-001", "title": "物流时效说明", "type": "物流规则", "version": "2.1", "status": "published", "text": "普通地区下单后 48 小时内发货，偏远地区物流时效可能增加 2-3 天。物流停滞超过 72 小时可联系客服登记催件。", "shop_id": "all", "acl": ["buyer", "agent", "manager", "admin"], "keywords": ["物流", "发货", "72小时", "催件"]},
            {"id": "kb-product-001", "title": "数码商品售后说明", "type": "商品资料", "version": "1.2", "status": "published", "text": "蓝牙耳机首次使用请完成配对并升级固件；如有断连，可先重置耳机并更换播放设备测试。", "shop_id": "all", "acl": ["buyer", "agent", "manager", "admin"], "keywords": ["蓝牙耳机", "断连", "固件", "重置"]},
            {"id": "kb-customer-001", "title": "客服服务规范", "type": "客服话术", "version": "1.0", "status": "published", "text": "客服应先核验订单归属，再引用有效政策回答；无法确认时应说明不确定性并转人工。", "shop_id": "all", "acl": ["agent", "manager", "admin"], "keywords": ["客服", "订单核验", "引用", "转人工"]},
            {"id": "kb-payment-001", "title": "支付与发货说明", "type": "交易规则", "version": "1.0", "status": "published", "text": "支付成功后系统生成订单并锁定库存；商家通常在 48 小时内发货。支付失败不会扣款，重复支付以订单幂等号为准。", "shop_id": "all", "acl": ["buyer", "agent", "manager", "admin"], "keywords": ["支付", "锁定库存", "重复支付", "幂等"]},
        ]

    def add_event(self, event: dict) -> None:
        with self.lock:
            self.events.append({"id": str(uuid4()), "created_at": now(), **event})

    def remember_idempotency(self, scope: str, key: str, value: dict) -> None:
        with self.lock:
            self.idempotency[f"{scope}:{key}"] = value

    def recall_idempotency(self, scope: str, key: str) -> dict | None:
        with self.lock:
            return self.idempotency.get(f"{scope}:{key}")

    def least_active_agent(self) -> str:
        """选择当前处理量最小的客服，并原子增加其负载。"""
        with self.lock:
            agent_id = min(self.agent_workloads, key=self.agent_workloads.get)
            self.agent_workloads[agent_id] += 1
            return agent_id


store = Store()
