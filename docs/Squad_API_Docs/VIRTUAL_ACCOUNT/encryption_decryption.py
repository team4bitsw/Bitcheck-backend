from Crypto.Cipher import AES
                  import base64
                  import hashlib
  
  
                  def _pad(s): return s + (AES.block_size - len(s) % AES.block_size) * chr(AES.block_size - len(s) % AES.block_size) 
                  def _cipher():
                      key = hashlib.md5(merchant_secret_key).hexdigest() # 32 character hexadecimal
                      iv = hashlib.md5(merchant_public_key).digest() # 16 byte binary
                      return AES.new(key=key, mode=AES.MODE_CBC, IV=iv)
  
                  def encrypt_token(data):
                      return _cipher().encrypt(_pad(data))
                      
                  def decrypt_token(data):
                      return _cipher().decrypt(data)
  
                  if __name__ == '__main__':
                      print('Python encrypt: ' + base64.b64encode(encrypt_token('dmyz.org')))
                      print('Python decrypt: ' + decrypt_token(base64.b64decode('FSfhJ/gk3iEJOPVLyFVc2Q==')))