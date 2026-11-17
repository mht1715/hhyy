import request from '../utils/request'

// 药品咨询接口
export const drugConsultApi = (productId, message, sessionId) => {
    return request.post('/agent/drug-consult', {
        product_id: productId,
        message: message,
        session_id: sessionId
    })
}