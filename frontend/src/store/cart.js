import {defineStore} from 'pinia'

export const useCartStore = defineStore('cart', {
    state: () => ({
        items: JSON.parse(localStorage.getItem('hhyy_cart') || '[]')
    }),
    getters: {
        totalCount: (state) => state.items.reduce((sum, item) => sum + item.quantity, 0),
        totalPrice: (state) => state.items.reduce((sum, item) => sum + item.price * item.quantity, 0)
    },
    actions: {
        addToCart(product, quantity = 1) {
            const existing = this.items.find(i => i.id === product.id)
            if (existing) {
                existing.quantity += quantity
            } else {
                this.items.push({...product, quantity})
            }
            this.save()
        },
        removeFromCart(id) {
            this.items = this.items.filter(i => i.id !== id)
            this.save()
        },
        clearCart() {
            this.items = []
            this.save()
        },
        save() {
            localStorage.setItem('hhyy_cart', JSON.stringify(this.items))
        }
    }
})