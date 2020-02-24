import triton
import torch.nn as nn
import torch
import torch.nn.functional as F

class _conv2d(torch.autograd.Function):

    @staticmethod
    def forward(ctx, input, weight, bias, 
                stride, padding, dilation, groups,
                acc_bitmask):
      assert dilation == (1, 1)
      assert groups == 1
      assert bias == None
      pad_h, pad_w = padding
      stride_h, stride_w = stride
      n, c, h, w = input.size()
      k, c, r, s = weight.size()
      # allocate output
      p = (h + 2*padding[0] - r)//stride[0] + 1
      q = (w + 2*padding[1] - s)//stride[1] + 1
      output = torch.empty((n, k, p, q), dtype=input.dtype, device=input.device)
      # padding
      if pad_h or pad_w:
        input = triton.ops._einsum.pad(input, [pad_w, pad_w, pad_h, pad_h])
      # convolution
      triton.ops.einsum(f'nc(h*stride_h + r - pad_h)(w*stride_w + s - pad_w),kcrs->nkhw', 
                        input, weight, mask=acc_bitmask,
                        output=output,
                        values = {'pad_h': pad_h,
                                  'stride_h': stride_h,
                                  'pad_w': pad_w,
                                  'stride_w': stride_w})
      # prepare backprop
      ctx.save_for_backward(input, weight)
      ctx.stride = stride
      ctx.padding = padding
      ctx.acc_bitmask = acc_bitmask
      # return
      return output
    
    @staticmethod
    def backward(ctx, dy):
      # retrieve contextual information
      input, weight = ctx.saved_tensors
      stride = ctx.stride
      padding = ctx.padding
      acc_bitmask = ctx.acc_bitmask
      # gradient of the input
      dx = None
      if ctx.needs_input_grad[0]:
        # dy must be padded
        n, k, p, q = dy.size()
        n, c, h, w = input.size()
        k, c, r, s = weight.size()
        dypad = triton.ops._einsum.pad(dy, [4, 4, 4, 4])
        # have to be careful here
        # the gradient of strided conv is a conv over a sparse image
        # which can be decomposed as a set of smaller convs
        dx = torch.empty_like(input)
        for offh in range(stride[0]):
          for offw in range(stride[1]):
            poffh = (offh + padding[0]) % stride[0]
            poffw = (offw + padding[1]) % stride[1]
            pad_h = int((padding[0] + (stride[0] - 1)*offh) / stride[0])
            pad_w = int((padding[1] + (stride[1] - 1)*offw) / stride[1])
            if offh >= r or offw >= s:
              dx[:, :, poffh::stride[0], poffw::stride[1]] = 0
            else:
              triton.ops.einsum(f'nk(h - r + pad_h)(w - s + pad_w),kcrs->nchw', 
                                 dypad[:, :, :, :], 
                                 weight[:, :, offh::stride[0], offw::stride[1]],
                                 output = dx[:, :, poffh::stride[0], poffw::stride[1]],
                                 mask = acc_bitmask,
                                 values = {'pad_h': pad_h,
                                           'pad_w': pad_w})
      # gradient for the weight
      dw = None
      if ctx.needs_input_grad[1]:
        dw = torch.empty_like(weight)
        triton.ops.einsum(f'nc(p*{stride[0]}+r-{padding[0]})(q*{stride[1]}+s-{padding[1]}),nkpq->kcrs', 
                           input, dy, output = dw, mask = acc_bitmask)
      return dx, dw, None, None, None, None, None, None
conv2d = _conv2d.apply

class Conv2d(nn.Conv2d):

    def __init__(self, in_channels, out_channels, kernel_size, stride=1,
                 padding=0, dilation=1, groups=1,
                 bias=True, padding_mode='zeros',
                 acc_bitmask = None):
        super(Conv2d, self).__init__(
            in_channels, out_channels, kernel_size, stride, padding, dilation,
            groups, bias, padding_mode)
        self.acc_bitmask = acc_bitmask

    def forward(self, input):
        #if self.kernel_size[0] == 3:
        #  return F.conv2d(input, self.weight, self.bias, self.stride, self.padding, self.dilation, self.groups)
        return conv2d(input, self.weight, self.bias, self.stride, 
                      self.padding, self.dilation, self.groups,
                      self.acc_bitmask)


def replace_conv2d(model, acc_bitmask = None):
    for child_name, child in model.named_children():
        if isinstance(child, nn.Conv2d):
            conv2d = Conv2d(child.in_channels, child.out_channels, child.kernel_size,
                            child.stride, child.padding, child.dilation, child.groups,
                            child.bias, child.padding_mode, 
                            acc_bitmask=acc_bitmask)
            for yparam, xparam in zip(conv2d.parameters(), child.parameters()):
                yparam.data.copy_(xparam.data)
            setattr(model, child_name, conv2d)
        else:
            replace_conv2d(child, acc_bitmask)