

__all__ = ['get_hashed_password', 'check_password']


try:
    import bcrypt


    def get_hashed_password(plain_text_password):
        # Hash a password for the first time
        #   (Using bcrypt, the salt is saved into the hash itself)
        return bcrypt.hashpw(plain_text_password, bcrypt.gensalt())


    def check_password(plain_text_password, hashed_password):
        # Check hashed password. Using bcrypt, the salt is saved into the hash itself
        return bcrypt.checkpw(plain_text_password, hashed_password)

except (ImportError, Exception):
    def get_hashed_password(plain_text_password):
        raise EnvironmentError('Must install bcrypt in order to use authentication!')

    def check_password(plain_text_password, hashed_password):
        raise EnvironmentError('Must install bcrypt in order to use authentication!')
