import psycopg2

class PostgreSQLPipeline:
    def __init__(self, postgres_host, postgres_db, postgres_user, postgres_password):
        self.postgres_host = postgres_host
        self.postgres_db = postgres_db
        self.postgres_user = postgres_user
        self.postgres_password = postgres_password
        
    @classmethod
    def from_crawler(cls, crawler):
        return cls(
            postgres_host=crawler.settings.get('POSTGRES_HOST', 'postgres'),
            postgres_db=crawler.settings.get('POSTGRES_DB', 'jobscraperdb'),
            postgres_user=crawler.settings.get('POSTGRES_USER', 'jobscraper'),
            postgres_password=crawler.settings.get('POSTGRES_PASSWORD', 'password')
        )
        
    def open_spider(self, spider):
        self.connection = psycopg2.connect(
            host=self.postgres_host,
            dbname=self.postgres_db,
            user=self.postgres_user,
            password=self.postgres_password
        )
        self.cursor = self.connection.cursor()
        
    def close_spider(self, spider):
        self.cursor.close()
        self.connection.close()
        
    def process_item(self, item, spider):
        sql = """
        INSERT INTO jobs (title, company, location, description, source_url, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        """
        self.cursor.execute(
            sql, 
            (
                item.get('title'), 
                item.get('company'), 
                item.get('location'), 
                item.get('description'),
                item.get('url')
            )
        )
        self.connection.commit()
        return item