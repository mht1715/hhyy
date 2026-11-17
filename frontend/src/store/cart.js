import {defineStore} from 'pinia'
import {getCartApi, addToCartApi, removeCartItemApi, clearCartApi, updateCartQuantityApi} from '../api/cart'
import {showToast} from 'vant'

export const useCartStore = defineStore('cart', {
    state: () => ({
        items: [],
        totalPrice: 0,
        totalCount: 0
    }),
    actions: {
        async fetchCart() {
            try {
                const res = await getCartApi()
                this.items = res.items
                this.calculateTotals()
            } catch (e) {
                this.items = []
                this.totalPrice = 0
                this.totalCount = 0
            }
        },
        // 新增一个计算方法，方便复用
        calculateTotals() {
            this.totalPrice = this.items.reduce((sum, item) => sum + item.price * item.quantity, 0)
            this.totalCount = this.items.reduce((sum, item) => sum + item.quantity, 0)
        },
        async add(productId, quantity = 1) {
            await addToCartApi(productId, quantity)
            await this.fetchCart()
        },
        async remove(itemId) {
            await removeCartItemApi(itemId)
            await this.fetchCart()
        },
        async clear() {
            await clearCartApi()
            await this.fetchCart()
        },
        // 【关键修复】静默更新数量
        async updateQuantity(itemId, quantity) {
            const item = this.items.find(i => i.id === itemId)
            if (item) {
                // 1. 先在本地更新，保证 UI 瞬间响应
                item.quantity = quantity
                this.calculateTotals()

                // 2. 后台静默发给服务器
                try {
                    await updateCartQuantityApi(itemId, quantity)
                } catch (e) {
                    // 如果失败了，重新拉取后端数据覆盖本地
                    await this.fetchCart()
                }
            }
        }
    }
})